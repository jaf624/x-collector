#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""制裁/管制/军演类一手硬料 RSS 候选验证（独立 workflow，海外节点跑）。
对每个逻辑源尝试多个候选 feed URL，取第一个能解析出 item/entry 的为可用，
结果写 data/hard_feed_probe.json，不直接改主配置，人工据结果再加入。"""
import urllib.request, ssl, json, os, datetime, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "hard_feed_probe.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# (逻辑源key, 规范名, cat, grade, host, [候选feed URL...])
CANDS = [
    ("treasury", "美国财政部新闻稿", "gov", "A", "home.treasury.gov", [
        "https://home.treasury.gov/news/press-releases/rss.xml"]),
    ("ofac", "美财政部OFAC制裁动态", "gov", "A", "ofac.treasury.gov", [
        "https://home.treasury.gov/news/press-releases/rss.xml?field_component_target_id=26",
        "https://ofac.treasury.gov/feed",
        "https://www.treasury.gov/resource-center/sanctions/Newsroom/Pages/rss.xml"]),
    ("bis", "美工业与安全局BIS出口管制", "gov", "A", "bis.doc.gov", [
        "https://www.bis.doc.gov/index.php/feed",
        "https://www.bis.doc.gov/?format=feed&type=rss"]),
    ("commerce", "美国商务部新闻稿", "gov", "B", "www.commerce.gov", [
        "https://www.commerce.gov/news/press-releases/rss.xml"]),
    ("centcom", "美军中央司令部", "gov", "A", "centcom.mil", [
        "https://www.centcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945",
        "https://www.centcom.mil/RSS/"]),
    ("indopacom", "美军印太司令部", "gov", "A", "indopacom.mil", [
        "https://www.pacom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1001",
        "https://www.indopacom.mil/RSS/"]),
    ("northcom", "美军北方司令部", "gov", "B", "northcom.mil", [
        "https://www.northcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1031",
        "https://www.northcom.mil/RSS/"]),
    ("southcom", "美军南方司令部", "gov", "B", "southcom.mil", [
        "https://www.southcom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=961",
        "https://www.southcom.mil/RSS/"]),
    ("spacecom", "美军太空司令部", "gov", "B", "spacecom.mil", [
        "https://www.spacecom.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1041",
        "https://www.spacecom.mil/RSS/"]),
    ("army", "美国陆军", "gov", "B", "www.army.mil", [
        "https://www.army.mil/rss/",
        "https://www.army.mil/feeds/rss/"]),
    ("navy", "美国海军", "gov", "B", "www.navy.mil", [
        "https://www.navy.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1067"]),
    ("af", "美国空军", "gov", "B", "www.af.mil", [
        "https://www.af.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1075"]),
    ("marines", "美国海军陆战队", "gov", "B", "www.marines.mil", [
        "https://www.marines.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1059"]),
    ("spaceforce", "美国太空军", "gov", "B", "www.spaceforce.mil", [
        "https://www.spaceforce.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1085"]),
    ("dvidshub", "DVIDS国防一手影像新闻", "osint", "B", "www.dvidshub.net", [
        "https://www.dvidshub.net/news/rss",
        "https://www.dvidshub.net/rss/news.xml"]),
    ("stripes", "星条旗报军事新闻", "media", "B", "www.stripes.com", [
        "https://www.stripes.com/rss.xml"]),
    ("japan_mod", "日本防卫省", "gov", "A", "www.mod.go.jp", [
        "https://www.mod.go.jp/e/whatsnew/rss.xml",
        "https://www.mod.go.jp/atla/rss.xml"]),
    ("korea_mnd", "韩国国防部", "gov", "B", "www.mnd.go.kr", [
        "https://www.mnd.go.kr/user/boardList.action?siteId=mnd&pageId=mnd0101000000&boardId=I_25039&findType=&findValue=&findHeader=&listUrl=&columnName=&columnValue=&categoryId=&ctgYn=&cmd=rss"]),
    ("australia_def", "澳大利亚国防部", "gov", "A", "www.defence.gov.au", [
        "https://www.defence.gov.au/news/rss",
        "https://news.defence.gov.au/rss"]),
    ("india_mod", "印度国防部", "gov", "C", "mod.gov.in", [
        "https://mod.gov.in/rss",
        "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&RegID=3"]),
    ("wassenaar", "瓦森纳协定出口管制", "gov", "A", "www.wassenaar.org", [
        "https://www.wassenaar.org/feed/"]),
    ("shape_nato", "北约盟军作战司令部SHAPE", "gov", "B", "shape.nato.int", [
        "https://shape.nato.int/rss",
        "https://ac.nato.int/rss"]),
]


def count_items(body):
    n = 0
    sample = ""
    try:
        root = ET.fromstring(body)
        for e in root.iter():
            t = e.tag.lower()
            if t.endswith("item") or t.endswith("entry"):
                n += 1
                if not sample:
                    tnode = None
                    for c in e:
                        if c.tag.lower().endswith("title"):
                            tnode = c
                            break
                    if tnode is not None and tnode.text:
                        sample = tnode.text.strip()[:80]
    except Exception:
        return -1, ""
    return n, sample


def probe_url(u, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/xml, atom+xml, text/xml, */*"})
            with urllib.request.urlopen(req, timeout=18, context=CTX) as r:
                body = r.read(800000).decode("utf-8", "ignore")
                n, sample = count_items(body)
                return {"url": u, "status": r.status, "items": n, "sample": sample}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(2 + attempt * 2)
                continue
            return {"url": u, "status": e.code, "items": 0, "err": "HTTP %s" % e.code}
        except Exception as e:
            if attempt < retries:
                time.sleep(2 + attempt * 2)
                continue
            return {"url": u, "status": -1, "items": 0, "err": str(e)[:80]}


def probe_source(c):
    key, name, cat, grade, host, urls = c
    tries = []
    chosen = None
    for u in urls:
        rec = probe_url(u)
        tries.append(rec)
        if rec.get("items", 0) > 0:
            chosen = rec
            break
    return {"key": key, "name": name, "cat": cat, "grade": grade, "host": host,
            "ok": chosen is not None,
            "feed_url": chosen["url"] if chosen else "",
            "items": chosen["items"] if chosen else 0,
            "sample": chosen.get("sample", "") if chosen else "",
            "tries": tries}


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(probe_source, c) for c in CANDS]
        for fu in as_completed(futs):
            r = fu.result()
            results.append(r)
            flag = "OK %2d条" % r["items"] if r["ok"] else "失效"
            print("%-12s %-22s %s %s" % (r["key"], flag, r["feed_url"][:60], r["sample"][:30]), flush=True)
    order = {c[0]: i for i, c in enumerate(CANDS)}
    results.sort(key=lambda r: order[r["key"]])
    ok = [r for r in results if r["ok"]]
    report = {"probed_at": datetime.datetime.utcnow().isoformat() + "Z",
              "total": len(results), "ok_count": len(ok),
              "ok_keys": [r["key"] for r in ok], "results": results}
    json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n可用 %d/%d，结果写 %s" % (len(ok), len(results), OUT), flush=True)


if __name__ == "__main__":
    main()
