#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完全免费的 X 优质提示词主动发现采集器（GitHub Actions 海外节点，零 Key / 零登录 / 零支付）。

多源冗余发现 tweet ID，任一源被限流不影响其它源：
  - HackerNews Algolia API（免费无 key、对云服务器友好）：近期 AI 提示词讨论里的 X 链接
  - Reddit JSON（免 key）：提示词相关板块/搜索里的 X 链接
  - SearXNG 公共实例池（聚合 Google/Bing/DuckDuckGo，多实例轮询 + 故障切换）：指定博主 + 关键词
  - Bing 网页（降密度、分片轮询）：兜底指定博主
发现的新 ID 统一用 collect.fetch_by_id（cdn.syndication 免登录）取正文/图/视频，
图片落地 data/images，累积去重写 data/x_feed.json，供国内服务器洗练入库。
"""
import os, re, json, time, ssl, gzip, random, base64, urllib.request, urllib.error, urllib.parse, datetime, pathlib
import collect

ROOT = pathlib.Path(__file__).resolve().parent
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
SEEN_F = ROOT / "data" / "discovered_ids.json"
CUR_F = ROOT / "data" / "discover_cursor.json"
MAX_FETCH = int(os.environ.get("FREE_DISCOVER_MAX", "60"))
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]
ID_RE = re.compile(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status(?:es)?/(\d{10,})')
SEARX_INSTANCES = [
    "https://searx.be", "https://search.sapti.me", "https://searx.tiekoetter.com", "https://opnxng.com",
    "https://priv.au", "https://search.hbubli.cc", "https://paulgo.io", "https://searxng.ch",
    "https://searx.ox2.fr", "https://search.inetol.net", "https://northboot.xyz", "https://s.mble.dk",
    "https://search.gcomm.ch", "https://search.rhscz.eu", "https://baresearch.org", "https://xo.wtf",
    "https://search.ononoki.org", "https://searx.darkness.services", "https://search.bus-hit.me",
    "https://search.mdosch.de", "https://searx.catfluori.de", "https://search.zzls.xyz",
]
HN_QUERIES = ["GPT image prompt", "midjourney prompt", "AI prompt engineering", "seedance video prompt",
              "image generation prompt", "ChatGPT prompt", "x.com prompt"]
RD_QUERIES = ["x.com prompt", "AI image prompt", "midjourney prompt", "GPT image prompt",
              "video prompt AI", "prompt engineering"]


def http(url, method="GET", data=None, timeout=15, accept="*/*", ua=None):
    headers = {"User-Agent": ua or random.choice(UAS), "Accept-Language": "en-US,en;q=0.9", "Accept": accept}
    body = urllib.parse.urlencode(data).encode() if data else None
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "ignore")


def extract_ids(text):
    out = {}
    for sn, tid in ID_RE.findall(text or ""):
        if sn.lower() not in ("i", "home", "search", "share", "intent", "s"):
            out[tid] = sn
    for raw in re.findall(r'uddg=([^&"\'<>]+)', text or ""):
        m = ID_RE.search(urllib.parse.unquote(raw))
        if m:
            out[m.group(2)] = m.group(1)
    for raw in re.findall(r'[?&]u=a1([A-Za-z0-9_\-]+)', text or ""):
        try:
            m = ID_RE.search(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore"))
            if m:
                out[m.group(2)] = m.group(1)
        except Exception:
            pass
    return out


# ---------- HackerNews (Algolia) ----------
def from_hackernews():
    found = {}
    ts = int(time.time()) - 4 * 86400
    for q in HN_QUERIES:
        try:
            url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(
                {"query": q, "tags": "story,comment", "numericFilters": f"created_at_i>{ts}", "hitsPerPage": 80})
            d = json.loads(http(url, timeout=15, accept="application/json"))
            for h in d.get("hits", []):
                blob = " ".join(str(h.get(k, "")) for k in ("title", "story_title", "url", "comment_text", "story_text"))
                found.update(extract_ids(blob))
        except Exception as e:
            print("[hn] fail", q, str(e)[:80], flush=True)
        time.sleep(1)
    print(f"[hn] 发现 {len(found)}", flush=True)
    return found


# ---------- Reddit ----------
def from_reddit():
    found = {}
    subs = ["", "r/PromptEngineering/", "r/StableDiffusion/", "r/midjourney/", "r/chatgpt/"]
    for sub in subs:
        for q in (RD_QUERIES[:3] if sub else RD_QUERIES):
            try:
                base = f"https://www.reddit.com/{sub}search.json"
                url = base + "?" + urllib.parse.urlencode({"q": q, "sort": "new", "limit": "60", "t": "week"})
                d = json.loads(http(url, timeout=15, accept="application/json",
                                   ua="Mozilla/5.0 (compatible; prompthub-research/1.0)"))
                for c in d.get("data", {}).get("children", []):
                    p = c.get("data", {})
                    blob = " ".join(str(p.get(k, "")) for k in ("title", "selftext", "url", "permalink"))
                    found.update(extract_ids(blob))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(8)
            except Exception:
                pass
            time.sleep(2.2)
    print(f"[reddit] 发现 {len(found)}", flush=True)
    return found


# ---------- SearXNG 实例池（自动收敛到可用实例，每查询最多试 3 个） ----------
_GOOD = []

def searx_query(q, dead, tries=3):
    cand = list(_GOOD) + [b for b in SEARX_INSTANCES if b not in _GOOD]
    random.shuffle([b for b in cand if b not in _GOOD])
    tried = 0
    for base in cand:
        if dead.get(base, 0) >= 2 or tried >= tries:
            continue
        tried += 1
        url = base + "/search?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "language": "en", "safesearch": "0"})
        try:
            txt = http(url, timeout=7, accept="application/json")
            if not txt.lstrip().startswith("{"):
                dead[base] = dead.get(base, 0) + 1
                continue
            d = json.loads(txt)
            got = {}
            for it in d.get("results", []):
                got.update(extract_ids(it.get("url", "")))
                got.update(extract_ids(it.get("content", "")))
            if base not in _GOOD:
                _GOOD.insert(0, base)
            return got
        except Exception:
            dead[base] = dead.get(base, 0) + 1
    return {}


def from_searx(queries):
    found, dead = {}, {}
    for i, q in enumerate(queries):
        got = searx_query(q, dead)
        found.update(got)
        print(f"[searx {i+1}/{len(queries)}] {q[:40]} -> +{len(got)}（好实例={_GOOD[:2]}）", flush=True)
        time.sleep(1.2)
    print(f"[searx] 合计发现 {len(found)}，可用实例 {_GOOD}", flush=True)
    return found


# ---------- Bing 分片兜底（低密度、长间隔，规避云 IP 软限流） ----------
def from_bing_shard(accounts, shard=4):
    cur = json.loads(CUR_F.read_text()) if CUR_F.exists() else {}
    idx = int(cur.get("bing_idx", 0))
    picked = [a for i, a in enumerate(accounts) if i % shard == idx % shard]
    cur["bing_idx"] = (idx + 1) % shard
    CUR_F.write_text(json.dumps(cur), encoding="utf-8")
    found = {}
    for a in picked:
        url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"q": f"(site:x.com/{a}/status OR site:twitter.com/{a}/status)", "count": "30", "setlang": "en-US", "cc": "US"})
        try:
            found.update(extract_ids(http(url, timeout=12)))
        except Exception as e:
            print("[bing] fail", a, str(e)[:70], flush=True)
        time.sleep(random.uniform(9.0, 13.0))
    print(f"[bing 分片 {idx}：{len(picked)}博主] 发现 {len(found)}", flush=True)
    return found


def load_seen():
    if SEEN_F.exists():
        try:
            return set(json.loads(SEEN_F.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def main():
    accounts = collect.read_lines(ROOT / "targets" / "accounts.txt")
    keywords = collect.read_lines(ROOT / "targets" / "keywords.txt")
    sx_queries = [f"site:x.com/{a}/status" for a in accounts] + [f"{k} site:x.com" for k in keywords]

    found = {}
    found.update(from_hackernews())
    found.update(from_reddit())
    found.update(from_searx(sx_queries))
    found.update(from_bing_shard(accounts))

    seen = load_seen()
    new_ids = [t for t in found if t not in seen]
    random.shuffle(new_ids)
    print(f"[discover] 多源合计 {len(found)}，新 ID {len(new_ids)}，本轮取前 {min(MAX_FETCH,len(new_ids))}", flush=True)

    recs = []
    for tid in new_ids[:MAX_FETCH]:
        r = collect.fetch_by_id(tid)
        if r and r.get("text_raw"):
            recs.append(r)
        seen.add(tid)
        time.sleep(1.1)
    print(f"[discover] 免登录接口取到 {len(recs)} 条，开始下图", flush=True)

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
    SEEN_F.parent.mkdir(exist_ok=True)
    SEEN_F.write_text(json.dumps(sorted(seen | set(found)), ensure_ascii=False), encoding="utf-8")
    print(f"[discover] 完成：取 {len(recs)}，新增 {added}，feed 累积 {len(feed)}", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print(extract_ids('<a href="https://x.com/ddjcxx/status/2099762659071795585">x</a><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftwitter.com%2Fvoxcatai%2Fstatus%2F2099296595007390135">d</a>'))
    else:
        main()
