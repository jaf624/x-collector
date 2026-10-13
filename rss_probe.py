#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测候选 RSS feed（GitHub Actions 美国节点直连，零 Jina）：报告 HTTP/条目数/最新日期/
涉华+国安主题命中数，挑出可直接加入 institute_sources.json 的源。workflow_dispatch 触发。"""
import re
import intel_collect as ic

TITLE_CN = re.compile(ic.TITLE_CHINA_RE, re.I)
TOPIC = re.compile(ic.TOPIC_RE, re.I)

CAND = [
    # —— 资源矿产 / 金属 / 矿业 ——
    ("Mining.com矿业", "media", "https://www.mining.com/feed/"),
    ("Kitco金属矿业", "media", "https://www.kitco.com/rss/KitcoNews.xml"),
    ("USGS新闻发布", "gov", "https://www.usgs.gov/news.xml"),
    # —— 能源 / 油气 / 航运 ——
    ("OilPrice能源资讯", "media", "https://oilprice.com/rss/main"),
    ("EIA能源信息署", "gov", "https://www.eia.gov/rss/todayinenergy.xml"),
    # —— 军事 / 国防 ——
    ("USNI海军学会", "media", "https://news.usni.org/feed"),
    ("Defense News", "media", "https://www.defensenews.com/arc/outboundfeeds/rss/"),
    ("Breaking Defense", "media", "https://breakingdefense.com/feed/"),
    ("The War Zone", "media", "https://www.twz.com/feeds/articles/all/index.xml"),
    ("Stars and Stripes", "media", "https://www.stripes.com/rss.xml"),
    ("美国防部新闻", "gov", "https://www.defense.gov/desktopmodules/ArticleCS/RSS.ashx?Site=941&max=30"),
    ("印太司令部", "gov", "https://www.pacom.mil/DesktopModules/ArticleCS/RSS.ashx?Site=1122&max=30"),
    # —— 美国官方 ——
    ("USTR贸易代表", "gov", "https://ustr.gov/feeds/news/rss.xml"),
    ("财政部新闻稿", "gov", "https://home.treasury.gov/news/press-releases/rss.xml"),
    ("能源部新闻", "gov", "https://www.energy.gov/feeds/latest-news.xml"),
    ("国务院新闻", "gov", "https://www.state.gov/feed/"),
    ("BIS工业安全局", "gov", "https://www.bis.gov/rss.xml"),
    ("白宫", "gov", "https://www.whitehouse.gov/feed/"),
    ("商务部新闻", "gov", "https://www.commerce.gov/news/rss.xml"),
    # —— 多边 / 盟友 ——
    ("WTO新闻", "gov", "https://www.wto.org/library/rss/latest_news_e.xml"),
    ("IMF新闻", "gov", "https://www.imf.org/external/rss/feed_rss.aspx"),
    ("IEA新闻", "gov", "https://www.iea.org/news/feed"),
    ("北约新闻", "gov", "https://www.nato.int/structur/rss/nato-en.xml"),
    ("欧盟贸易总署", "gov", "https://policy.trade.ec.europa.eu/news_en.rss"),
    ("日本经产省METI", "gov", "https://www.meti.go.jp/english/rss/index.rss"),
    # —— 亚太/英文媒体 ——
    ("日经亚洲", "media", "https://asia.nikkei.com/rss/feed/nar"),
    ("日经亚洲政治", "media", "https://asia.nikkei.com/rss/feed/politics"),
    ("南华早报", "media", "https://www.scmp.com/rss/91/feed"),
    ("外交学者", "media", "https://thediplomat.com/feed/"),
    ("亚洲时报", "media", "https://asiatimes.com/feed/"),
]

usable = []
for name, cat, url in CAND:
    st, body = ic.feed_get(url, timeout=20)
    if st != 200 or not body or body.startswith("EXC"):
        print(f"[FAIL] {name:14s} HTTP {st} {url}")
        continue
    try:
        items = ic.parse_rss_items(body, url)
    except Exception as e:
        print(f"[PARSE] {name:14s} 解析失败 {str(e)[:60]}")
        continue
    hits = []
    dates = []
    for it in items:
        if it.get("date"):
            dates.append(it["date"])
        ti, tx = it.get("title") or "", it.get("text") or ""
        if TITLE_CN.search(ti + " " + tx[:800]) and TOPIC.search(ti + " " + tx[:1500]):
            hits.append(ti)
    latest = max(dates).isoformat() if dates else "?"
    flag = "OK  " if len(hits) >= 1 else "NOCH"
    print(f"[{flag}] {name:14s} 条目{len(items):3d} 涉华国安{len(hits):2d} 最新{latest} {url}")
    for h in hits[:4]:
        print(f"        · {h[:78]}")
    if len(hits) >= 1 and len(items) >= 3:
        usable.append((name, cat, url, len(items), len(hits)))

print("\n========== 可直接采纳（200 且条目>=3 且涉华国安>=1）==========")
for name, cat, url, n, h in usable:
    print(f"  {name}\t{cat}\t{url}\t条目{n} 命中{h}")
