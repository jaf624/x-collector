#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""官方动作采集器（OFAC 制裁 / BIS 出口管制）。

纯代码：直连公开页面 + 正则解析，不使用任何模型。
产出 data/gov_action_feed.json，字段与 intel_sync 入库预期对齐。
第一版：列表解析 + 标题/类型中文翻译，先验证链路；正文抓取随后迭代。
"""
import os, re, ssl, json, datetime, urllib.request, urllib.error

import intel_collect as ic

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "gov_action_feed.json")

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

OFAC_URL = "https://ofac.treasury.gov/recent-actions"
BIS_URL = ("https://www.bis.gov/news-updates/search?content_type=press_release"
           "&sort_by=created&sort_order=DESC")

DATE_EN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(20\d{2})", re.I)
ROW_BLOCK = re.compile(r'search-result[^>]*>(.*?)(?=search-result|</div>\s*</div>\s*$)', re.I | re.S)
HREF_TITLE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
TAG = re.compile(r"<[^>]+>")


def fetch(url, tries=3, timeout=20):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                body = r.read(700000).decode("utf-8", "ignore")
            if len(body) > 1000:
                return body
        except Exception as e:
            last = str(e)[:70]
    print("  fetch fail %s %s" % (url, last), flush=True)
    return ""


def iso_date(en):
    m = DATE_EN.search(en or "")
    if not m:
        return ""
    return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(1).title()], int(m.group(2)))


def clean(t):
    return re.sub(r"\s+", " ", TAG.sub("", t)).strip()


def parse_ofac(html):
    out = []
    # 按详情链接逐条提取，再在其所在窗口找日期
    for m in re.finditer(r'<a[^>]+href="(/recent-actions/\d+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        path, title = m.group(1), clean(m.group(2))
        if not title:
            continue
        window = html[m.end():m.end() + 260]
        published = iso_date(window)
        out.append({
            "url": "https://ofac.treasury.gov" + path,
            "title": title, "published": published, "kind": "OFAC制裁",
            "source": "美国财政部海外资产控制办公室",
        })
    return out


def parse_bis(html):
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(/news-updates/\d+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        path, title = m.group(1), clean(m.group(2))
        if not title or path in seen:
            continue
        seen.add(path)
        window = html[max(0, m.start()-300):m.start()] + html[m.end():m.end()+200]
        published = iso_date(window)
        out.append({
            "url": "https://www.bis.gov" + path,
            "title": title, "published": published, "kind": "BIS出口管制",
            "source": "美国商务部工业与安全局",
        })
    return out


def to_feed_item(r):
    zh_title = ic.gtx_translate(r["title"]) or r["title"]
    return {
        "url": r["url"], "title": r["title"], "source": r["source"],
        "lang": "en", "route": "gov_action", "cat": "institute",
        "published": r["published"] or datetime.date.today().isoformat(),
        "summary": zh_title, "content": zh_title,
        "quality_score": 60, "usable": False,  # 仅标题，正文补齐后再置可用
        "media_types": [], "handling": r["kind"],
    }


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rows = []
    ofac_html = fetch(OFAC_URL)
    if ofac_html:
        rows += parse_ofac(ofac_html)
        print("OFAC 解析 %d 条" % len(parse_ofac(ofac_html)), flush=True)
    bis_html = fetch(BIS_URL)
    if bis_html:
        rows += parse_bis(bis_html)
        print("BIS 解析 %d 条" % len(parse_bis(bis_html)), flush=True)
    # 去重（按 URL）并翻译
    items, uniq = [], set()
    for r in rows:
        if r["url"] in uniq:
            continue
        uniq.add(r["url"])
        print("  译 %s | %s" % (r["kind"], r["title"][:60]), flush=True)
        items.append(to_feed_item(r))
    json.dump(items, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("GOV_ACTION_COLLECT_DONE 共 %d 条 -> %s" % (len(items), OUT), flush=True)


if __name__ == "__main__":
    main()
