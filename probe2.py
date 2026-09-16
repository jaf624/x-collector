#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深挖 timeline-profile 服务端渲染 HTML，提取用户最新推文 ID。"""
import json, ssl, re, urllib.request, urllib.error, math

CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
def b36(n):
    s=""
    while n: s=DIGITS[n%36]+s; n//=36
    return s or "0"
def token(tid):
    x=(int(tid)/1e15)*math.pi; ip=int(x); fp=x-ip; s=b36(ip)
    if fp>0:
        s+="."
        for _ in range(16):
            fp*=36; d=int(fp); s+=DIGITS[d]; fp-=d
            if fp==0: break
    return s.replace("0","").replace(".","")
def get(url):
    req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"text/html,application/json","Accept-Language":"en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return r.status, r.read().decode("utf-8","ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8","ignore")
    except Exception as e:
        return None, repr(e)

for USER in ["ddjcxx", "voxcatai", "nanyuan0412"]:
    print("="*25, USER, "="*25)
    s, html = get(f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{USER}")
    print("status:", s, "html len:", len(html))
    # 提取 status/数字 链接里的推文 ID
    ids = re.findall(r'/status(?:es)?/(\d{15,25})', html)
    ids = list(dict.fromkeys(ids))
    print("tweet ids found:", len(ids), ids[:10])
    # 看是否有 __NEXT_DATA__ / __INITIAL_STATE__
    for key in ["__NEXT_DATA__", "__INITIAL_STATE__", "timeline", "tweet_results"]:
        print(f"  contains {key}:", key in html)
    # 打印一段含 status 的上下文
    m = re.search(r'.{60}/status(?:es)?/\d{15,25}.{60}', html)
    if m: print("  context:", m.group(0)[:200])

    # 如果拿到 ID，用 tweet-result 取第一条全文验证
    if ids:
        tid = ids[0]
        s2, b2 = get(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&lang=zh-cn&token={token(tid)}")
        try:
            d=json.loads(b2)
            print("  >> first tweet by", d.get("user",{}).get("screen_name"), ":", (d.get("text") or "")[:100].replace(chr(10)," "))
            print("  >> photos:", len(d.get("photos",[])), "fav:", d.get("favorite_count"))
        except Exception as e:
            print("  >> tweet-result parse fail:", s2, b2[:120])
