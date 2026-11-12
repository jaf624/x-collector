#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 OFAC/BIS 页面原始 HTML 存 data，并打印条目结构片段供解析器开发。"""
import ssl, urllib.request, os, re

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

PAGES = [
    ("ofac", "https://ofac.treasury.gov/recent-actions"),
    ("bis", "https://www.bis.gov/news-updates/search?content_type=press_release&sort_by=created&sort_order=DESC"),
]
os.makedirs("data/govhtml", exist_ok=True)
for name, url in PAGES:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8", "ignore")
    open("data/govhtml/%s.html" % name, "w", encoding="utf-8").write(html)
    print("saved %s %d bytes" % (name, len(html)))

# 打印 OFAC 第一个含日期的条目上下文
ofac = open("data/govhtml/ofac.html", encoding="utf-8").read()
m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d", ofac)
if m:
    s = max(0, m.start() - 600)
    print("=" * 30, "OFAC 条目结构")
    print(ofac[s:m.start() + 300])
