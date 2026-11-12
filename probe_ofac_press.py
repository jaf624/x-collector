#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ssl, urllib.request, re
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8", "ignore")


# 1. press-releases 列表
plist = get("https://ofac.treasury.gov/press-releases")
print("press列表长度", len(plist))
links = re.findall(r'href="(/press-releases/\d+)"[^>]*>([^<]{15,})<', plist)[:8]
for u, t in links:
    print("  ", u, "|", t.strip()[:70])
# 2. 取第一篇看正文结构
if links:
    detail = get("https://ofac.treasury.gov" + links[0][0])
    print("=" * 30, "详情长度", len(detail))
    i = detail.find("field--name-body")
    seg = detail[i:i+5000] if i > 0 else detail
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg))
    print(txt[:1800])
