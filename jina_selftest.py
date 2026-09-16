#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性：实测 r.jina.ai 代抓境外媒体/长文页面、s.jina.ai 搜索的真实 token 消耗。"""
import os, json, ssl, time, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def call(tag, url, accept):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}",
                                               "Accept": accept, "User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
            body = r.read().decode("utf-8", "ignore")
            tok = r.headers.get("x-usage-tokens", "?")
            print(f"\n### {tag}\nHTTP {r.status}  耗时{round(time.time()-t0,1)}s  x-usage-tokens={tok}  体积{len(body)}字符")
            try:
                d = json.loads(body).get("data", {})
                txt = d.get("text", "") or ""
                imgs = d.get("images", []) or []
                links = d.get("links", []) or []
                print(f"  text {len(txt)}字符 | images {len(imgs)} | links {len(links)}")
                print("  片段:", txt[:200].replace("\n", " "))
            except Exception:
                print("  非JSON(文本模式) 前200:", body[:200].replace("\n", " "))
    except urllib.error.HTTPError as e:
        print(f"\n### {tag}\nHTTP {e.code} {e.read().decode('utf-8','ignore')[:200]}")
    except Exception as e:
        print(f"\n### {tag}\nEXC {repr(e)[:160]}")


# 境外媒体首页/栏目（代表"打开一个反华媒体站点"）
call("VOA中文首页", "https://r.jina.ai/https://www.voachinese.com/", "application/json")
call("BBC中文首页", "https://r.jina.ai/https://www.bbc.com/zhongwen/simp", "application/json")
# 一篇长文基准（维基"中国"词条，篇幅≈一篇深度报道/报告）
call("维基长文(中国词条)", "https://r.jina.ai/https://zh.wikipedia.org/wiki/%E4%B8%AD%E5%9B%BD", "application/json")
# 搜索：代表"搜境外媒体相关报道"
q = urllib.parse.quote("China security site:voachinese.com")
req_url = "https://s.jina.ai/" + q + "?num=5"
call("搜索(num=5)", req_url, "application/json")
print("\nSELFTEST_DONE")
