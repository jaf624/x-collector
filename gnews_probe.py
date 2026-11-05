#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gnews_probe.py — 在 Actions 环境里对同一批 Google News 链接做三法对照，结果写入 data/gnews_probe.json"""
import json
import re
import urllib.request

FEED = "data/intel_feed.json"
OUT = "data/gnews_probe.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def method_redirect(u):
    try:
        import requests
        r = requests.get(u, timeout=20, allow_redirects=True,
                         headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        return {"status": r.status_code, "final": r.url[:160], "len": len(r.text)}
    except Exception as e:
        return {"err": type(e).__name__ + ":" + str(e)[:60]}


def method_article_page(u):
    try:
        html = get(u)
        sig = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        from collections import Counter
        links = re.findall(r'href="(https?://[^"]+)"', html)
        hosts = Counter(re.sub(r"https?://([^/]+).*", r"\1", u) for u in links)
        nongoogle = [u for u in links if "google" not in u][:4]
        return {"html_len": len(html), "has_sig": bool(sig), "has_ts": bool(ts),
                "n_au": html.count("data-n-au"), "n_a": html.count("data-n-a"),
                "top_hosts": hosts.most_common(6),
                "nongoogle": [u[:120] for u in nongoogle]}
    except Exception as e:
        return {"err": type(e).__name__ + ":" + str(e)[:60]}


def method_batch(u):
    try:
        import gnews_resolve
        real, why = gnews_resolve.resolve_verbose(u)
        return {"real": (real or "")[:160], "why": why}
    except Exception as e:
        return {"err": type(e).__name__ + ":" + str(e)[:60]}


def method_batch2(u):
    try:
        import gnews_resolve
        real, why = gnews_resolve.resolve_verbose2(u)
        return {"real": (real or "")[:160], "why": why}
    except Exception as e:
        return {"err": type(e).__name__ + ":" + str(e)[:60]}


def main():
    items = json.load(open(FEED, encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", [])
    cand = [x for x in items if "news.google.com" in (x.get("url") or "")
            and len((x.get("content") or "").strip()) < 200][:6]
    res = []
    for x in cand:
        u = x["url"]
        res.append({"title": (x.get("title") or "")[:50],
                    "redirect": method_redirect(u),
                    "page": method_article_page(u),
                    "batch": method_batch(u),
                    "batch2": method_batch2(u)})
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("probed", len(res))


if __name__ == "__main__":
    main()
