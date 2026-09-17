#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性探测：Jina 对社媒/请愿平台的可抓性、links-summary 省 token 效果、watch 类搜索召回。
仅在 GitHub Actions 美国 runner 手动 dispatch 运行，不写库。"""
import os, json, ssl, datetime
import urllib.request, urllib.parse, urllib.error

KEY = os.environ["JINA_KEY"].strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def req(url, accept="text/plain", extra=None, timeout=90):
    h = {"Authorization": f"Bearer {KEY}", "Accept": accept,
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}
    if extra:
        h.update(extra)
    r = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=CTX) as x:
            return x.status, x.read().decode("utf-8", "ignore"), dict(x.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300], dict(e.headers or {})
    except Exception as e:
        return None, "EXC " + repr(e)[:160], {}


def reader(u, extra=None):
    st, body, hdr = req("https://r.jina.ai/" + u, extra=extra)
    return st, body, hdr.get("x-usage-tokens", "?")


print("=" * 20, "A. reader 平台可达性", "=" * 20, flush=True)
for name, u in [
    ("telegram公开频道(cgtn)", "https://t.me/s/cgtnofficial"),
    ("reddit r/China", "https://www.reddit.com/r/China/"),
    ("youtube视频页(机制测试)", "https://www.youtube.com/watch?v=aqz-KE-bpKQ"),
    ("change.org请愿搜索", "https://www.change.org/search?q=China"),
    ("x状态页(对照,预期403/空)", "https://x.com/ddjcxx/status/2099762659071795585"),
]:
    st, body, tok = reader(u)
    print(f"\n[{name}] HTTP{st} tokens={tok} len={len(body)}", flush=True)
    print("  " + body[:220].replace("\n", " "), flush=True)

print("\n" + "=" * 20, "B. links-summary 省token对照", "=" * 20, flush=True)
u = "https://www.voachinese.com/p/6197.html"
_, b1, t1 = reader(u)
_, b2, t2 = reader(u, extra={"X-With-Links-Summary": "true"})
print(f"普通: tokens={t1} len={len(b1)}", flush=True)
print(f"links-summary: tokens={t2} len={len(b2)}", flush=True)
print("links-summary 尾部样例:\n" + b2[-700:], flush=True)

print("\n" + "=" * 20, "C. watch 扩展类搜索召回", "=" * 20, flush=True)
qs = [
    "anti-China protest rally overseas",
    "China covert disinformation deepfake campaign",
    "Uyghur Hong Kong Tibetan activist new coalition group",
    "Chinese dissident Telegram channel",
    "site:youtube.com China dissident activist",
    "site:reddit.com China influence operation",
]
after = (datetime.datetime.utcnow().date() - datetime.timedelta(days=7)).isoformat()
for q in qs:
    qq = urllib.parse.quote(f"{q} after:{after}")
    st, body, hdr = req(f"https://s.jina.ai/{qq}?num=4", "application/json")
    print(f"\n[Q] {q}  HTTP{st} tokens={hdr.get('x-usage-tokens','?')}", flush=True)
    try:
        for it in json.loads(body).get("data", [])[:4]:
            print("  - " + (it.get("url", "") or "")[:72] + " | " + (it.get("title", "") or "")[:64], flush=True)
    except Exception:
        print("  parse fail " + body[:160], flush=True)

print("\nPROBE_INTEL_DONE", flush=True)
