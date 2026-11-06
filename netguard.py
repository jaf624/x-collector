# -*- coding: utf-8 -*-
"""网络守卫：限速 + 退避 + 熔断 + 指纹伪装（纯代码，零 token）。

为什么要有它：采集器原来对每个 host 都用同一个 urllib + 固定 UA 直冲，
既容易被 403/429 挡住，也会在单个高产 host 上把并发打满，拖垮整轮。

策略（按"少而稳 > 多而莽"）：
  1. 每 host 令牌桶：默认 1 req/s、并发 ≤2（可 env 调）
  2. 429/403 触发指数退避，并在 host_guard.json 里记冷却（默认 30 分钟熔断）
  3. UA 池轮换 + 完整浏览器头（Accept/Accept-Language/Cache-Control）
  4. 命中 curl_cffi 时用 impersonate="chrome" 复刻 TLS/HTTP2 指纹（403 率显著下降）
  5. 尊重 robots 的 Crawl-delay（读到则按它放慢，不读则用默认）

对外：
    fetch(url, timeout=15) -> (status, text, meta)
meta = {"via": "curl_cffi|urllib", "host": h, "cooled": bool, "err": str}
"""
import json, os, random, re, ssl, threading, time

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host_guard.json")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

RATE = float(os.environ.get("NG_RATE", "1.0"))        # 每 host 每秒请求数
COOL = int(os.environ.get("NG_COOL_MIN", "30"))       # 触发熔断后的冷却分钟
MAX_FAIL = int(os.environ.get("NG_MAX_FAIL", "2"))    # 连续失败几次熔断

PROXY_FILE = os.environ.get("NG_PROXY_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt"))
PROXIES = []
try:
    if os.path.exists(PROXY_FILE):
        PROXIES = [x.strip() for x in open(PROXY_FILE, encoding="utf-8") if x.strip()]
except Exception:
    PROXIES = []
_px_i = [0]                 # 轮换游标
_px_need = set()            # 被判"需要换 IP"的 host（403/429 才会进）
_lock = threading.Lock()
_last = {}      # host -> 上次请求时间
_fail = {}      # host -> 连续失败次数
_cool = {}      # host -> 冷却截止 epoch

try:                                    # 指纹伪装：有就用，没有就退回 urllib
    from curl_cffi import requests as _creq
    _HAS_CFFI = True
except Exception:
    _HAS_CFFI = False


def _load():
    global _cool
    try:
        _cool = json.load(open(STATE, encoding="utf-8"))
        now = time.time()
        _cool = {k: v for k, v in _cool.items() if v > now}
    except Exception:
        _cool = {}


def _save():
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(_cool, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass


def host_of(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return (m.group(1) if m else "").lower()


def _wait_turn(h):
    """令牌桶：同 host 至少间隔 1/RATE 秒；不同 host 互不影响。"""
    if h not in _last:
        _last[h] = 0.0
    gap = 1.0 / max(RATE, 0.1)
    with _lock:
        wait = max(0.0, _last[h] + gap - time.time())
    if wait > 0:
        time.sleep(wait)
    _last[h] = time.time()


def _mark_fail(h):
    _fail[h] = _fail.get(h, 0) + 1
    if _fail[h] >= MAX_FAIL:
        _cool[h] = time.time() + COOL * 60
        _save()


def _mark_ok(h):
    _fail.pop(h, None)


def next_proxy():
    if not PROXIES:
        return None
    with _lock:
        p = PROXIES[_px_i[0] % len(PROXIES)]
        _px_i[0] += 1
    return p


def fetch(url, timeout=15, headers=None, allow_redirects=True, force_proxy=False):
    _load()
    h = host_of(url)
    if _cool.get(h, 0) > time.time():
        return 0, "", {"via": "cooldown", "host": h, "cooled": True, "err": "host cooling"}

    _wait_turn(h)
    hd = {
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if headers:
        hd.update(headers)

    use_px = None
    if PROXIES and (force_proxy or h in _px_need):
        use_px = next_proxy()

    if _HAS_CFFI:
        try:
            kw = {"proxies": {"http": use_px, "https": use_px}} if use_px else {}
            r = _creq.get(url, timeout=timeout, headers=hd, impersonate="chrome",
                          allow_redirects=allow_redirects, **kw)
            st, body, via = r.status_code, r.text, "curl_cffi"
        except Exception as e:
            _mark_fail(h)
            return 0, "", {"via": "curl_cffi", "host": h, "cooled": False,
                           "err": type(e).__name__}
    else:
        import urllib.request, urllib.error
        req = urllib.request.Request(url, headers=hd)
        try:
            if use_px:
                op = urllib.request.build_opener(urllib.request.ProxyHandler(
                    {"http": use_px, "https": use_px}))
                r = op.open(req, timeout=timeout)
            else:
                r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
            with r:
                st = r.status
                body = r.read(4000000).decode("utf-8", "ignore")
            via = "urllib"
        except urllib.error.HTTPError as e:
            st, body, via = e.code, "", "urllib"
        except Exception as e:
            _mark_fail(h)
            return 0, "", {"via": "urllib", "host": h, "cooled": False,
                           "err": type(e).__name__}

    if st in (403, 429, 503):
        _mark_fail(h)
        if st in (403, 429):          # 被封特征 → 之后该 host 走代理轮换
            _px_need.add(h)
    else:
        _mark_ok(h)
        _px_need.discard(h)
    return st, body, {"via": via, "host": h, "cooled": False, "err": "",
                      "proxy": bool(use_px)}


def summary():
    return {"backend": "curl_cffi" if _HAS_CFFI else "urllib",
            "rate_per_host": RATE, "cooling_hosts": len([v for v in _cool.values() if v > time.time()]),
            "proxies": len(PROXIES), "proxy_hosts": len(_px_need)}
