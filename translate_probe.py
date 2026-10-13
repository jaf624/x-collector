# -*- coding: utf-8 -*-
"""海外节点诊断 Google 免费翻译各端点可用性，打印状态码与原始响应。"""
import urllib.request, urllib.parse, ssl, json

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
q = "Lynas plans Brazil rare earths plant with state support"
qe = urllib.parse.quote(q)

endpoints = [
    ("gtx.googleapis single",
     "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + qe),
    ("clients5 t dict-chrome",
     "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl=zh-CN&q=" + qe),
    ("translate.google.com single",
     "https://translate.google.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + qe),
]
for name, u in endpoints:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            body = r.read().decode("utf-8", "ignore")
            print("=" * 12, name, "HTTP", r.status, "=" * 12)
            print(body[:400])
            print()
    except Exception as e:
        print("=" * 12, name, "ERR", repr(e), "=" * 12)
print("GTX_PROBE_DONE")
