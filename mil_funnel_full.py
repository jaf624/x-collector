#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整漏斗分析：拉取 8 个 .mil + PIB 已验证 feed，用采集器同口径判定每条去向。"""
import os, re, json, ssl, urllib.request, datetime
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import intel_collect as ic

TOPIC = re.compile(ic.TOPIC_RE, re.I)
TITLE_CHINA = re.compile(ic.TITLE_CHINA_RE, re.I)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "mil_funnel_full.json")

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

FEEDS = [
    ("centcom", "https://www.centcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("southcom", "https://www.southcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("navy", "https://www.navy.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("af", "https://www.af.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("marines", "https://www.marines.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("spaceforce", "https://www.spaceforce.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("northcom", "https://www.northcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("spacecom", "https://www.spacecom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&max=20"),
    ("pib", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&RegID=3"),
]


def _txt(e, names):
    for c in e:
        tag = c.tag.lower()
        if any(tag.endswith(n) for n in names):
            return (c.text or "").strip()
    return ""


def parse_feed(key, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        body = r.read(600000)
    root = ET.fromstring(body)
    items = []
    for e in root.iter():
        if e.tag.lower().endswith("item") or e.tag.lower().endswith("entry"):
            title = _txt(e, ["title"])
            link = _txt(e, ["link"]) or ""
            if not link:
                for c in e:
                    if c.tag.lower().endswith("link") and c.get("href"):
                        link = c.get("href"); break
            desc = _txt(e, ["description", "summary", "encoded"])
            items.append({"title": title, "link": link, "desc": desc})
    return key, items


def verdict(it):
    title = it["title"]
    text = title + " " + it["desc"][:1500]
    if ic.soft_news(title):
        return "soft"
    if not TOPIC.search(text):
        return "topic"
    if TITLE_CHINA.search(title + " " + it["desc"][:800]):
        return "china"
    combo = title + " " + it["desc"]
    geo = bool(ic.INDO_HOT_RE.search(combo)
               or (ic.INDO_ALLY_RE.search(combo) and not ic.EURO_EX_RE.search(combo)))
    if geo and ic.MIL_POSTURE_RE.search(combo):
        return "indo"
    return "other"


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(parse_feed, k, u) for k, u in FEEDS]
        for fu in as_completed(futs):
            key, items = fu.result()
            rows = []
            for it in items:
                rows.append({"verdict": verdict(it), "title": it["title"][:110]})
            data[key] = rows
    json.dump({"analyzed_at": datetime.datetime.utcnow().isoformat() + "Z", "data": data},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 控制台汇总
    from collections import Counter
    for key in [k for k, _ in FEEDS]:
        c = Counter(r["verdict"] for r in data.get(key, []))
        print("%-10s %d条 %s" % (key, len(data.get(key, [])), dict(c)))
    print("written", OUT)


if __name__ == "__main__":
    main()
