#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性：查询 Jina key 的余额/用量/套餐信息。"""
import os, json, ssl, urllib.request, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
ENDPOINTS = [
    "https://api.jina.ai/v1/credits",
    "https://api.jina.ai/v1/usage",
    "https://api.jina.ai/v1/me",
    "https://api.jina.ai/v1/user/info",
    "https://api.jina.ai/v1/billing/usage",
    "https://api.jina.ai/v1/dashboard/credits",
]
for u in ENDPOINTS:
    req = urllib.request.Request(u, headers={"Authorization": f"Bearer {KEY}",
                                             "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            print(f"\n### {u}\nHTTP {r.status}\n{r.read().decode('utf-8','ignore')[:800]}")
    except urllib.error.HTTPError as e:
        print(f"\n### {u}\nHTTP {e.code} {e.read().decode('utf-8','ignore')[:200]}")
    except Exception as e:
        print(f"\n### {u}\nEXC {repr(e)[:150]}")
print("\nSELFTEST_DONE")
