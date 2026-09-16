#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性自检：带 JINA_KEY 验证 s.jina.ai 能否搜到 X、r.jina.ai 能否代抓 X（含计时）。"""
import os, re, json, time, ssl, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
ID_RE = re.compile(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status(?:es)?/(\d{10,})')
print("JINA_KEY 前12位:", (KEY[:12] + "...") if KEY else "(空)")


def req(url, accept, timeout=120):
    r = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {KEY}", "Accept": accept,
        "User-Agent": "Mozilla/5.0", "X-Respond-Format": "text"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=CTX) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore"), round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:400], round(time.time() - t0, 1)
    except Exception as e:
        return None, "EXC " + repr(e)[:300], round(time.time() - t0, 1)


def search(q):
    print(f"\n=== 搜索: {q} ===")
    st, body, sec = req("https://s.jina.ai/" + urllib.parse.quote(q), "application/json")
    print(f"HTTP {st}  耗时{sec}s  长度{len(body)}")
    ids = {}
    try:
        data = json.loads(body).get("data", []) or []
        print("data 条数:", len(data))
        for it in data[:8]:
            u = it.get("url", "")
            m = ID_RE.search(u + " " + it.get("content", "")[:500])
            tag = "  <<<X " + m.group(2) if m else ""
            print("  -", it.get("title", "")[:60], "|", u[:95], tag)
            if m:
                ids[m.group(2)] = m.group(1)
    except Exception:
        print("非JSON:", body[:500])
    print(">>> X 命中 ID 数:", len(ids), list(ids)[:10])


search("site:x.com/ddjcxx/status")
search("GPT image prompt site:x.com")

print("\n=== 代抓单条 X 推文 (r.jina.ai, json) ===")
st, body, sec = req("https://r.jina.ai/https://x.com/ddjcxx/status/2099762659071795585",
                    "application/json")
print(f"HTTP {st}  耗时{sec}s  长度{len(body)}")
try:
    d = json.loads(body).get("data", {})
    print("title:", d.get("title", "")[:120])
    print("text 片段:", (d.get("text", "") or "")[:400].replace("\n", " "))
    imgs = [i for i in (d.get("images", []) or []) if "twimg" in str(i)]
    print("twimg 图片数:", len(imgs), imgs[:4])
except Exception:
    print("非JSON:", body[:500])
print("\nSELFTEST_DONE")
