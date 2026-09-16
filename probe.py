#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 X 免登录接口：在海外 runner 上测哪些接口不需要 auth_token 就能拿数据。"""
import json, ssl, urllib.request, urllib.error, math

CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

def b36(n):
    if n == 0: return "0"
    s=""
    while n: s=DIGITS[n%36]+s; n//=36
    return s
def token(tid):
    x=(int(tid)/1e15)*math.pi
    ip=int(x); fp=x-ip; s=b36(ip)
    if fp>0:
        s+="."
        for _ in range(16):
            fp*=36; d=int(fp); s+=DIGITS[d]; fp-=d
            if fp==0: break
    return s.replace("0","").replace(".","")

def get(url, headers=None):
    h={"User-Agent":UA,"Accept":"*/*","Accept-Language":"en-US,en;q=0.9"}
    if headers: h.update(headers)
    req=urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return r.status, r.read().decode("utf-8","ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","ignore")[:300]
    except Exception as e:
        return None, repr(e)[:300]

TID="2099735654641070183"
USER="ddjcxx"

print("="*20, "1) tweet-result (已知可用)", "="*20)
s,b = get(f"https://cdn.syndication.twimg.com/tweet-result?id={TID}&lang=zh-cn&token={token(TID)}",
          {"Referer":"https://platform.twitter.com/"})
print("status:", s, "len:", len(b))
try:
    d=json.loads(b); print("text:", d.get("text","")[:80])
except: print(b[:200])

print("="*20, "2) profile timeline widget (免登录?)", "="*20)
for url in [
    f"https://cdn.syndication.twimg.com/widgets/timelines/profile?screen_name={USER}&lang=en",
    f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{USER}",
    f"https://cdn.syndication.twimg.com/widgets/timelines/profile?screen_name={USER}&suppress_response_codes=true&lang=en",
]:
    s,b = get(url, {"Referer":"https://platform.twitter.com/","Accept":"text/html,application/json"})
    print(f"[{s}] {url[:90]}")
    print("   len:", len(b), "| head:", b[:120].replace(chr(10)," "))

print("="*20, "3) 搜索 widget (免登录?)", "="*20)
for url in [
    "https://cdn.syndication.twimg.com/widgets/timelines/search?query=prompt%20engineering&lang=en",
    "https://syndication.twitter.com/srv/timeline-search?q=GPT%20image%20prompt",
]:
    s,b = get(url, {"Referer":"https://platform.twitter.com/"})
    print(f"[{s}] {url[:90]}")
    print("   len:", len(b), "| head:", b[:120].replace(chr(10)," "))
