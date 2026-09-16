#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性：探测 s.jina.ai 响应头里的 token 计量/限流，并对比结果数量参数对体积的影响。"""
import os, json, ssl, urllib.request, urllib.parse, urllib.error, time

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def probe(tag, url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {KEY}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
            body = r.read().decode("utf-8", "ignore")
            print(f"\n### {tag}\nHTTP {r.status}  耗时{round(time.time()-t0,1)}s  体积{len(body)}字符")
            for k, v in r.headers.items():
                lk = k.lower()
                if any(x in lk for x in ("ratelimit", "rate-limit", "token", "limit", "usage", "cost", "bill", "remain", "credit", "quota")):
                    print(f"  H {k}: {v}")
            try:
                d = json.loads(body).get("data", [])
                print("  data条数:", len(d))
            except Exception:
                pass
    except urllib.error.HTTPError as e:
        print(f"\n### {tag}\nHTTP {e.code}: {e.read().decode('utf-8','ignore')[:300]}")
    except Exception as e:
        print(f"\n### {tag}\nEXC {repr(e)[:200]}")


q = urllib.parse.quote("site:x.com/ddjcxx/status")
probe("默认(10条)", f"https://s.jina.ai/{q}")
probe("num=3", f"https://s.jina.ai/{q}?num=3")
probe("count=3", f"https://s.jina.ai/{q}?count=3")
print("\nSELFTEST_DONE")
