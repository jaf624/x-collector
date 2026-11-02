#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按 search_categories 的细分题材关键词，用 Google News RSS（免费、无需 token）
全网检索新闻，追加到 data/intel_feed.json。
跑在 GitHub Actions（境外 runner），每 2 小时一次。
"""
import os, re, json, time, hashlib, datetime, urllib.request, urllib.parse, xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(ROOT, "data", "intel_feed.json")
SRC = os.path.join(ROOT, "targets", "intel_sources.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.read()
    except Exception as e:
        print("  [gnews] fail %s: %s" % (url[:60], str(e)[:60]), flush=True)
        return b""

def gnews_search(q, n=8):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    body = fetch(url, 20)
    if not body:
        return []
    out = []
    try:
        root = ET.fromstring(body)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            src_el = item.find("source")
            src = (src_el.text or "").strip() if src_el is not None else "Google News"
            if title and link:
                out.append({"title": title, "url": link, "pub": pub, "src": src})
            if len(out) >= n:
                break
    except Exception as e:
        print("  [parse] fail: %s" % str(e)[:60], flush=True)
    return out

def main():
    cfg = json.load(open(SRC, encoding="utf-8"))
    topics = cfg.get("search_categories", [])
    feed = json.load(open(FEED, encoding="utf-8")) if os.path.exists(FEED) else []
    existing = set(x.get("url","") for x in feed)
    existing_titles = set(x.get("title","")[:60] for x in feed)
    now = datetime.datetime.utcnow().isoformat()
    added = 0
    for tp in topics:
        cat = tp.get("cat","")
        q = tp.get("q","")
        if not q:
            continue
        for art in gnews_search(q, n=5):
            u = art["url"]; t = art["title"]
            if u in existing or t[:60] in existing_titles:
                continue
            if len(t) < 12:
                continue
            hid = hashlib.md5(u.encode()).hexdigest()[:16]
            feed.append({
                "id": "gn_" + hid,
                "title": t,
                "url": u,
                "source": art["src"],
                "lang": "en",
                "cat": cat,
                "route": "gnews_topic",
                "summary": "",
                "content": "",
                "published": art["pub"],
                "fetched_at": now,
                "quality_score": 50,
                "usable": 0,
                "needs_deepdive": 1,
                "forwarded": 0,
                "category_key": cat,
                "handling": "",
            })
            existing.add(u); existing_titles.add(t[:60])
            added += 1
        time.sleep(0.5)
    # 保留最近 3000 条
    feed = feed[-3000:]
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False)
    print("Google News RSS 题材检索: 新增 %d 条, feed 总计 %d" % (added, len(feed)))

if __name__ == "__main__":
    main()
