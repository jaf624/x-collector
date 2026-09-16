#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完全免费的 X 主动发现采集器（GitHub Actions 海外节点运行，零 Key / 零登录 / 零支付）。

链路：
  1) 用必应 / DuckDuckGo 网页搜索，主动发现 targets 里"博主最新推文"和"关键词最新推文"的 status 链接
     （覆盖 x.com 与 twitter.com 两种域名；解析明文链接 + 搜索引擎跳转链接里的真实 URL）。
  2) 对发现的新推文 ID，复用 collect.fetch_by_id（cdn.syndication 免登录公开接口）取正文/图/视频。
  3) 图片落地 data/images（raw 地址，国内可达），累积去重写 data/x_feed.json，供国内服务器洗练入库。

不依赖任何 API Key / 账号 / cookie；多引擎 + 重试兜底；每轮只取有限数量新推文，保证在 Actions 时限内。
"""
import os, re, json, time, ssl, html, base64, urllib.request, urllib.error, urllib.parse, datetime, pathlib
import collect

ROOT = pathlib.Path(__file__).resolve().parent
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
SEEN_F = ROOT / "data" / "discovered_ids.json"
MAX_FETCH = int(os.environ.get("FREE_DISCOVER_MAX", "60"))   # 每轮最多新取多少条，控制 Actions 时长
MAX_PER_QUERY = 25
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]
ID_RE = re.compile(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status(?:es)?/(\d{10,})')


def http(url, method="GET", data=None, timeout=25):
    headers = {"User-Agent": UAS[int(time.time()) % len(UAS)], "Accept-Language": "en-US,en;q=0.9"}
    body = urllib.parse.urlencode(data).encode() if data else None
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read().decode("utf-8", "ignore")


def _b64d(s):
    try:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad).decode("utf-8", "ignore")
    except Exception:
        return ""


def extract_ids(text):
    """从搜索结果 HTML 里提取 (screen_name, tweet_id)；兼容明文链接与 Bing/DDG 跳转链接。"""
    out = {}
    # 1) 明文 x/twitter status 链接
    for sn, tid in ID_RE.findall(text):
        if sn.lower() not in ("i", "home", "search", "share", "intent"):
            out[tid] = sn
    # 2) DDG 的 uddg= 跳转
    for raw in re.findall(r'uddg=([^&"\'<>]+)', text):
        target = urllib.parse.unquote(raw)
        m = ID_RE.search(target)
        if m:
            out[m.group(2)] = m.group(1)
    # 3) Bing ck/a 的 u=a1<base64> 跳转
    for raw in re.findall(r'[?&]u=a1([A-Za-z0-9_\-]+)', text):
        target = _b64d(raw)
        m = ID_RE.search(target)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def bing(q):
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": q, "count": "30", "setlang": "en-US", "cc": "US", "form": "QBLH"})
    try:
        return extract_ids(http(url))
    except Exception as e:
        print("[bing] fail", q[:40], str(e)[:80], flush=True); return {}


def ddg(q, lite=False):
    base = "https://lite.duckduckgo.com/lite/" if lite else "https://html.duckduckgo.com/html/"
    try:
        if lite:
            txt = http(base + "?" + urllib.parse.urlencode({"q": q}))
        else:
            txt = http(base, method="POST", data={"q": q})
        return extract_ids(txt)
    except Exception as e:
        print("[ddg%s] fail" % ("-lite" if lite else ""), q[:40], str(e)[:80], flush=True); return {}


def discover(q):
    merged = {}
    for fn in (bing, lambda x: ddg(x), lambda x: ddg(x, lite=True)):
        merged.update(fn(q))
        time.sleep(2.0)
        if len(merged) >= MAX_PER_QUERY:
            break
    return dict(list(merged.items())[:MAX_PER_QUERY])


def load_seen():
    if SEEN_F.exists():
        try:
            return set(json.loads(SEEN_F.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(s):
    SEEN_F.parent.mkdir(exist_ok=True)
    SEEN_F.write_text(json.dumps(sorted(s), ensure_ascii=False), encoding="utf-8")


def main():
    accounts = collect.read_lines(ROOT / "targets" / "accounts.txt")
    keywords = collect.read_lines(ROOT / "targets" / "keywords.txt")
    queries = [f"(site:x.com/{a}/status OR site:twitter.com/{a}/status)" for a in accounts]
    queries += [f"{k} site:x.com" for k in keywords]

    found = {}
    for i, q in enumerate(queries):
        got = discover(q)
        for tid, sn in got.items():
            found.setdefault(tid, sn)
        print(f"[discover {i+1}/{len(queries)}] {q[:45]} -> 累计发现 {len(found)} 条", flush=True)
        time.sleep(1.5)

    seen = load_seen()
    new_ids = [t for t in found if t not in seen]
    print(f"[discover] 本轮发现 {len(found)}，其中新 ID {len(new_ids)}，取前 {min(MAX_FETCH,len(new_ids))} 条走免登录接口", flush=True)

    recs = []
    for tid in new_ids[:MAX_FETCH]:
        r = collect.fetch_by_id(tid)
        if r and r.get("text_raw"):
            recs.append(r); print("  [fetch] ok", tid, r["screen_name"])
        else:
            print("  [fetch] miss", tid)
        seen.add(tid)
        time.sleep(1.2)

    collect.localize_media(recs)
    OUT = collect.OUT
    old = {}
    if OUT.exists():
        try:
            old = {x["x_id"]: x for x in json.loads(OUT.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    added = 0
    for r in recs:
        if r["x_id"] not in old:
            added += 1
        old[r["x_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    save_seen(seen | set(found.keys()))
    print(f"[discover] 完成：取 {len(recs)}，新增 {added}，feed 累积 {len(feed)}", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sample = '<a href="https://x.com/ddjcxx/status/2099762659071795585">x</a> <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftwitter.com%2Fvoxcatai%2Fstatus%2F2099296595007390135">d</a>'
        print("selftest extract:", extract_ids(sample))
    else:
        main()
