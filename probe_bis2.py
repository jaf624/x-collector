#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ssl, urllib.request, urllib.error, re, time, json
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
URL = "https://www.bis.gov/news-updates/search?content_type=press_release&sort_by=created&sort_order=DESC"

html = ""
for attempt in range(4):
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=35, context=CTX) as r:
            html = r.read().decode("utf-8", "ignore")
            print("attempt", attempt, "status", r.status, "len", len(html))
        if len(html) > 5000:
            break
    except Exception as e:
        print("attempt", attempt, "err", str(e)[:80])
    time.sleep(3)

links = list(dict.fromkeys(re.findall(r'href="(/news-updates/\d[^"]*)"', html)))
print("detail links", len(links), links[:5])
if links:
    i = html.find(links[0])
    print("=" * 30)
    print(html[max(0, i-500):i+450])
# 日期呈现
dates = re.findall(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}", html)
print("dates sample", dates[:3])
