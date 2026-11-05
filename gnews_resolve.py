#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gnews_resolve.py — 纯代码把 news.google.com/rss/articles 还原成真实出版社 URL

原理（不依赖任何 API key、不用模型）：
1) 取 article 页 HTML，从 <c-wiz> 上读出签名 data-n-a-sg 与时间戳 data-n-a-ts；
2) 以 f.req=<JSON> 形式 POST 到 https://news.google.com/_/DotsSplashUi/data/batchexecute；
3) 响应是 "garturlreq" 包裹的数组，里面即真实 URL（http 开头）。

记忆引擎早前结论"base64 只解出 AU_ token"是只做了第 1 步的一半；batchexecute 必须带签名与时间戳才认。
"""
import json
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = "https://news.google.com"
BATCH = BASE + "/_/DotsSplashUi/data/batchexecute"


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                              "Accept-Language": "en-US,en;q=0.9"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _post_batch(article_id, sig, ts, timeout=15):
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,'
             'null,null,0,1],"%s",%s,"%s"]]' % (article_id, ts, sig))
    body = "f.req=" + urllib.parse.quote(json.dumps([["Fbv4je", inner]]))
    req = urllib.request.Request(BATCH, data=body.encode(), headers={
        "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def resolve_verbose(u, timeout=15):
    """返回 (real_url, 阶段码)，用于诊断。"""
    if not u or "news.google.com" not in u:
        return u, "not_gnews"
    m = re.search(r"/articles/([^?/]+)", u)
    if not m:
        return None, "no_article_id"
    aid = m.group(1)
    try:
        html = _get("%s/articles/%s" % (BASE, aid), timeout)
    except Exception as e:
        return None, "html_err:" + type(e).__name__
    if len(html) < 300:
        return None, "html_short:%d" % len(html)
    sig = re.search(r'data-n-a-sg="([^"]+)"', html)
    ts = re.search(r'data-n-a-ts="([^"]+)"', html)
    if not sig or not ts:
        return None, "no_sig:%s" % ("c-wiz_found" if "data-n-a-" in html else "no_marker")
    try:
        resp = _post_batch(aid, sig.group(1), ts.group(1), timeout)
    except Exception as e:
        return None, "post_err:" + type(e).__name__
    if not resp or len(resp) < 50:
        return None, "post_short:%d" % len(resp or "")
    hit = re.search(r'"(https?://(?![^"]*news\.google)[^"]+)"', resp)
    if not hit:
        return None, "no_url:%d" % len(resp)
    return hit.group(1).replace("\\u003d", "=").replace("\\u0026", "&"), "ok"


def resolve(u, timeout=15):
    """返回真实 URL；失败返回 None。"""
    if not u or "news.google.com" not in u:
        return u
    m = re.search(r"/articles/([^?/]+)", u)
    if not m:
        return None
    aid = m.group(1)
    try:
        html = _get("%s/articles/%s" % (BASE, aid), timeout)
        sig = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        if not (sig and ts):
            return None
        resp = _post_batch(aid, sig.group(1), ts.group(1), timeout)
        hit = re.search(r'"(https?://(?![^"]*news\.google)[^"]+)"', resp)
        return hit.group(1).replace("\\u003d", "=").replace("\\u0026", "&") if hit else None
    except Exception:
        return None
