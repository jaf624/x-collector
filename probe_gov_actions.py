#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 OFAC/BIS 官方动作页面在 Actions 节点的可抓取性与可解析条目数。"""
import ssl, json, re, urllib.request, urllib.error, os, datetime

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

TARGETS = [
    ("ofac_recent", "https://ofac.treasury.gov/recent-actions"),
    ("ofac_press", "https://ofac.treasury.gov/press-releases"),
    ("bis_news", "https://www.bis.gov/news-updates/search?content_type=press_release&sort_by=created&sort_order=DESC"),
    ("bis_all", "https://www.bis.gov/news-updates"),
]

# 日期模式（英文月份 + 日）
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}",
    re.I)
# 指向具体动作/新闻的链接
LINK_RE = re.compile(r'href="([^"]*(?:recent-actions|news-updates|press-releases)[^"]*)"', re.I)


def probe(name, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            html = r.read(500000).decode("utf-8", "ignore")
            st = r.status
    except urllib.error.HTTPError as e:
        return {"name": name, "status": e.code, "len": 0, "dates": 0, "links": 0}
    except Exception as e:
        return {"name": name, "status": -1, "err": str(e)[:80]}
    dates = len(set(DATE_RE.findall(html)))
    links = len(set(LINK_RE.findall(html)))
    return {"name": name, "status": st, "len": len(html),
            "date_hits": len(DATE_RE.findall(html)), "link_hits": links,
            "has_designation": ("designation" in html.lower() or "sanction" in html.lower())}


def main():
    out = []
    for name, url in TARGETS:
        r = probe(name, url)
        out.append(r)
        print(json.dumps(r, ensure_ascii=False))
    os.makedirs("data", exist_ok=True)
    json.dump({"probed_at": datetime.datetime.utcnow().isoformat() + "Z", "results": out},
              open("data/gov_action_probe.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("written data/gov_action_probe.json")


if __name__ == "__main__":
    main()
