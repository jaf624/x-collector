#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import ssl, urllib.request, re
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
url = "https://ofac.treasury.gov/recent-actions/20261104"
req = urllib.request.Request(url, headers={"User-Agent": UA})
html = urllib.request.urlopen(req, timeout=30, context=CTX).read().decode("utf-8", "ignore")
i = html.find("field__item")
seg = html[i:]
k = 0
# 不剥 ul；按文档顺序遍历所有 p/li/h 元素
for pm in re.finditer(r"<(p|li|h[1-4])([^>]*)>([\s\S]*?)</\1>", seg):
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", pm.group(3))).strip()
    if txt:
        k += 1
        cls = re.search(r'class="([^"]*)"', pm.group(2))
        print("%02d [%s%s] %s" % (k, pm.group(1),
                                  (" " + cls.group(1)[:30]) if cls else "", txt[:110]))
