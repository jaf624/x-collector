#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬料 RSS 自动发现：抓每个目标站点新闻入口 HTML，解析官方声明的
<link rel="alternate" type="application/rss+xml/atom+xml"> 及含 rss/feed 的链接，
再逐个验证 items>0，输出每个逻辑源真实可用 feed。海外节点跑，结果写 data。"""
import urllib.request, urllib.error, ssl, json, os, re, time, html as ihtml
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "hard_feed_discover.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# (key, 规范名, cat, grade, host, 新闻入口HTML)
SITES = [
    ("treasury", "美国财政部新闻稿", "gov", "A", "home.treasury.gov", "https://home.treasury.gov/news/press-releases"),
    ("ofac", "美财政部OFAC制裁动态", "gov", "A", "ofac.treasury.gov", "https://ofac.treasury.gov/"),
    ("bis", "美工业与安全局BIS出口管制", "gov", "A", "bis.doc.gov", "https://www.bis.doc.gov/index.php/si-news-room"),
    ("commerce", "美国商务部新闻稿", "gov", "B", "www.commerce.gov", "https://www.commerce.gov/news"),
    ("indopacom", "美军印太司令部", "gov", "A", "indopacom.mil", "https://www.pacom.mil/News/"),
    ("northcom", "美军北方司令部", "gov", "B", "northcom.mil", "https://www.northcom.mil/News/"),
    ("spacecom", "美军太空司令部", "gov", "B", "spacecom.mil", "https://www.spacecom.mil/News/"),
    ("army", "美国陆军", "gov", "B", "www.army.mil", "https://www.army.mil/news/"),
    ("af", "美国空军", "gov", "B", "www.af.mil", "https://www.af.mil/News/"),
    ("marines", "美国海军陆战队", "gov", "B", "www.marines.mil", "https://www.marines.mil/News/"),
    ("spaceforce", "美国太空军", "gov", "B", "www.spaceforce.mil", "https://www.spaceforce.mil/News/"),
    ("dvidshub", "DVIDS国防一手影像新闻", "osint", "B", "www.dvidshub.net", "https://www.dvidshub.net/news"),
    ("stripes", "星条旗报军事新闻", "media", "B", "www.stripes.com", "https://www.stripes.com/"),
    ("japan_mod", "日本防卫省", "gov", "A", "www.mod.go.jp", "https://www.mod.go.jp/e/"),
    ("australia_def", "澳大利亚国防部", "gov", "A", "www.defence.gov.au", "https://www.defence.gov.au/news/"),
    ("wassenaar", "瓦森纳协定出口管制", "gov", "A", "www.wassenaar.org", "https://www.wassenaar.org/"),
    ("shape_nato", "北约盟军作战司令部SHAPE", "gov", "B", "shape.nato.int", "https://shape.nato.int/"),
]

_LINK_ALT = re.compile(r"<link[^>]*rel=[\"']alternate[\"'][^>]*>", re.I)
_HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
_TYPE = re.compile(r"type=[\"'](application/(?:rss|atom)\+xml)[\"']", re.I)
_A_HREF = re.compile(r"<a[^>]*href=[\"']([^\"']*(?:rss|feed|atom)[^\"']*)[\"']", re.I)


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.geturl(), r.read(600000).decode("utf-8", "ignore")


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
                    for c in e:
                        if c.tag.lower().endswith("title") and c.text:
                            sample = c.text.strip()[:80]
                            break
    except Exception:
        return -1, ""
    return n, sample


def verify_feed(u):
    try:
        req = urllib.request.Request(u, headers={
            "User-Agent": UA, "Accept": "application/rss+xml, application/xml, atom+xml, */*"})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            body = r.read(500000).decode("utf-8", "ignore")
            n, sample = count_items(body)
            return r.status, n, sample
    except urllib.error.HTTPError as e:
        return e.code, 0, ""
    except Exception as e:
        return -1, 0, str(e)[:50]


def discover(site):
    key, name, cat, grade, host, entry = site
    rec = {"key": key, "name": name, "cat": cat, "grade": grade, "host": host,
           "entry": entry, "candidates": [], "ok": False, "feed_url": "",
           "items": 0, "sample": "", "page_status": None, "err": ""}
    try:
        st, final_url, page = http_get(entry)
        rec["page_status"] = st
        found = []
        for m in _LINK_ALT.finditer(page):
            tag = m.group(0)
            if _TYPE.search(tag):
                hm = _HREF.search(tag)
                if hm:
                    found.append(urllib.parse.urljoin(final_url, ihtml.unescape(hm.group(1))))
        for m in _A_HREF.finditer(page):
            found.append(urllib.parse.urljoin(final_url, ihtml.unescape(m.group(1))))
        # 去重、保序
        uniq = []
        for u in found:
            if u not in uniq:
                uniq.append(u)
        for u in uniq[:8]:
            fst, n, sample = verify_feed(u)
            c = {"url": u, "status": fst, "items": n, "sample": sample if isinstance(sample, str) else ""}
            rec["candidates"].append(c)
            if n > 0 and not rec["ok"]:
                rec.update(ok=True, feed_url=u, items=n, sample=sample)
    except urllib.error.HTTPError as e:
        rec["err"] = "HTTP %s" % e.code
    except Exception as e:
        rec["err"] = str(e)[:80]
    return rec


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(discover, s) for s in SITES]
        for fu in as_completed(futs):
            r = fu.result()
            results.append(r)
            if r["ok"]:
                print("OK  %-11s %3d条 %s" % (r["key"], r["items"], r["feed_url"][:70]))
            else:
                print("失  %-11s page=%s %s 候选%d" %
                      (r["key"], r["page_status"], r["err"], len(r["candidates"])))
    order = {s[0]: i for i, s in enumerate(SITES)}
    results.sort(key=lambda r: order[r["key"]])
    ok = [r for r in results if r["ok"]]
    json.dump({"discovered_at": datetime.datetime.utcnow().isoformat() + "Z",
               "total": len(results), "ok_count": len(ok),
               "ok_keys": [r["key"] for r in ok], "results": results},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n发现可用 %d/%d，写 %s" % (len(ok), len(results), OUT))


if __name__ == "__main__":
    main()
