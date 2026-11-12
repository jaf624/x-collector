#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ssl, urllib.request, re
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
URLS = [
    "https://ofac.treasury.gov/recent-actions/20261105",
    "https://ofac.treasury.gov/recent-actions/20261109",
]
for url in URLS:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        html = urllib.request.urlopen(req, timeout=25, context=CTX).read().decode("utf-8", "ignore")
        print("=" * 40, url, "len", len(html))
        # 找主内容容器
        for cls in ["field--name-body", "node__content", "field__item", "main-content"]:
            i = html.find(cls)
            if i > 0:
                print("found container", cls, "at", i)
                seg = re.sub(r"<[^>]+>", " ", html[i:i+1200])
                print(re.sub(r"\s+", " ", seg)[:900])
                break
    except Exception as e:
        print(url, "ERR", str(e)[:80])
