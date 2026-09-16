#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探测：在美国 runner 上确认哪些免费源能真正发现/代抓 X 推文。手动 workflow 触发。"""
import urllib.request, urllib.parse, urllib.error, ssl, json, re

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
ID = re.compile(r'(?:x|twitter)\.com/[A-Za-z0-9_]{1,20}/status(?:es)?/(\d{10,})')


def get(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300]
    except Exception as e:
        return None, "EXC " + repr(e)[:160]


# 1) Jina 搜索
q = urllib.parse.quote("site:x.com GPT image prompt")
st, body = get(f"https://s.jina.ai/{q}", {"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
print("\n[1] s.jina.ai search HTTP", st)
try:
    data = json.loads(body).get("data", [])
    hits = []
    for it in data:
        m = ID.search(it.get("url", "") + " " + it.get("content", ""))
        if m:
            hits.append((m.group(1), it.get("url", "")[:90]))
    print("  data条数", len(data), " X命中", len(hits))
    for h in hits[:5]:
        print("   ", h)
except Exception:
    print("  非JSON:", body[:300])

# 2) Jina Reader 代抓单条 X 推文
st, body = get("https://r.jina.ai/https://x.com/ddjcxx/status/2099762659071795585",
               {"Accept": "text/plain", "User-Agent": "Mozilla/5.0"})
print("\n[2] r.jina.ai tweet HTTP", st, " 长度", len(body))
print("  片段:", repr(body[:280]))

# 3) Reddit 匿名搜索
st, body = get("https://www.reddit.com/search.json?" + urllib.parse.urlencode(
    {"q": "AI image prompt x.com", "limit": "25", "sort": "new"}),
    {"User-Agent": "prompthub-research/1.0"})
print("\n[3] reddit HTTP", st)
try:
    ch = json.loads(body).get("data", {}).get("children", [])
    ids = set()
    for c in ch:
        p = c.get("data", {})
        m = ID.search(str(p.get("selftext", "")) + str(p.get("url", "")))
        if m:
            ids.add(m.group(1))
    print("  children", len(ch), " X命中", len(ids))
except Exception:
    print("  非JSON:", body[:200])

# 4) SearXNG 抽样
for base in ["https://priv.au", "https://searx.be", "https://opnxng.com", "https://search.sapti.me"]:
    u = base + "/search?" + urllib.parse.urlencode({"q": "site:x.com/ddjcxx/status", "format": "json"})
    st, body = get(u, {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}, timeout=12)
    n = 0
    try:
        for it in json.loads(body).get("results", []):
            if ID.search(it.get("url", "")):
                n += 1
    except Exception:
        pass
    print(f"\n[4] searx {base} HTTP {st} X命中 {n}")

print("\nPROBE_DONE")
