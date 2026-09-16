#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性：验证国安情报代抓流水线可行性。
1) r.jina.ai Markdown 模式抓媒体栏目首页 -> 能否拿到最新文章链接/标题/时间
2) 代抓一篇具体文章 -> 正文是否完整
3) s.jina.ai 搜索 + 时间限定(after:) -> 是否返回最近几天结果
"""
import os, re, json, ssl, time, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def call(url, accept="text/plain", timeout=120, extra=None):
    h = {"Authorization": f"Bearer {KEY}", "Accept": accept, "User-Agent": "Mozilla/5.0"}
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read().decode("utf-8", "ignore")
            return r.status, body, r.headers.get("x-usage-tokens", "?"), round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:300], "?", round(time.time() - t0, 1)
    except Exception as e:
        return None, "EXC " + repr(e)[:200], "?", round(time.time() - t0, 1)


# 1) 栏目首页 Markdown
print("=" * 30, "1) VOA中文首页(Markdown)", "=" * 30)
st, body, tok, sec = call("https://r.jina.ai/https://www.voachinese.com/")
print(f"HTTP {st} {sec}s tokens={tok} 长度={len(body)}")
print(body[:1600])
links = []
for m in re.findall(r'https?://www\.voachinese\.com/a/[^\s\)\]]+\.html', body):
    if m not in links:
        links.append(m)
print("\n提取到文章链接数:", len(links))
for u in links[:6]:
    print("  ", u)

# 2) 代抓第一篇具体文章正文
if links:
    print("\n" + "=" * 30, "2) 代抓文章正文", "=" * 30)
    st, body, tok, sec = call("https://r.jina.ai/" + links[0])
    print(f"{links[0]}\nHTTP {st} {sec}s tokens={tok} 长度={len(body)}")
    print("正文前1200字:\n", body[:1200])

# 3) 搜索 + 时间限定（最近几天）
print("\n" + "=" * 30, "3) 搜索限定 after:2026-09-14", "=" * 30)
q = urllib.parse.quote("China (Taiwan OR military OR sanctions OR espionage OR semiconductor) after:2026-09-14")
st, body, tok, sec = call("https://s.jina.ai/" + q + "?num=6", accept="application/json")
print(f"HTTP {st} {sec}s tokens={tok}")
try:
    for it in json.loads(body).get("data", [])[:6]:
        print("\n字段:", list(it.keys()))
        print("  title:", it.get("title", "")[:90])
        print("  url  :", it.get("url", "")[:110])
        print("  time :", it.get("publishedTime", it.get("published_time", "无")))
        print("  desc :", (it.get("description") or it.get("content", ""))[:160].replace("\n", " "))
except Exception as e:
    print("解析失败:", e, body[:400])
print("\nINTEL_SELFTEST_DONE")
