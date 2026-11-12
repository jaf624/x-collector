#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ssl, urllib.request, re
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
url = "https://ofac.treasury.gov/recent-actions/20261104"
req = urllib.request.Request(url, headers={"User-Agent": UA})
html = urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8", "ignore")
print("field__item 出现次数:", len(re.findall("field__item", html)))
print("field--name-body 位置:", [m.start() for m in re.finditer("field--name-body", html)])
# 定位正文关键句
for kw in ("shadow fleet", "is issuing", "General License", "MENU"):
    pos = [m.start() for m in re.finditer(re.escape(kw), html, re.I)][:3]
    print("关键词 %r 位置:" % kw, pos)
# 从最后一个 field--name-body（正文）开始 dump
bps = [m.start() for m in re.finditer("field--name-body", html)]
if bps:
    seg = html[bps[-1]:bps[-1] + 4000]
    print("=" * 30, "正文容器片段（去标签）")
    print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg))[:2500])
