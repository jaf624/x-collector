#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""".mil DNN ArticleCS RSS 参数探测：对每个目标 host 尝试多种 RSS.ashx 参数与
/RSS 路径，找出真实能解析出 item 的端点。海外节点跑，结果写 data。"""
import urllib.request, urllib.error, ssl, json, os, datetime, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "mil_rss_probe.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# (key, host, 已知可能Site编号)
HOSTS = [
    ("centcom", "www.centcom.mil", 945),
    ("southcom", "www.southcom.mil", 961),
    ("navy", "www.navy.mil", 1067),
    ("af", "www.af.mil", 1075),
    ("marines", "www.marines.mil", 1059),
    ("spaceforce", "www.spaceforce.mil", 1085),
    ("northcom", "www.northcom.mil", 1031),
    ("spacecom", "www.spacecom.mil", 1041),
    ("indopacom", "www.indopacom.mil", 1001),
]


def param_urls(host, site):
    base = "https://%s/DesktopModules/ArticleCS/RSS.ashx" % host
    return [
        base,
        base + "?ContentType=1",
        base + "?max=20",
        base + "?ContentType=1&max=20",
        base + "?ContentType=1&Site=%d" % site,
        "https://%s/RSS" % host,
        "https://%s/RSS/" % host,
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
                    for c in e:
                        if c.tag.lower().endswith("title") and c.text:
                            sample = c.text.strip()[:70]
                            break
    except Exception:
        return -1, ""
    return n, sample


def probe(u):
    try:
        req = urllib.request.Request(u, headers={
            "User-Agent": UA, "Accept": "application/rss+xml, application/xml, atom+xml, */*"})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            body = r.read(400000).decode("utf-8", "ignore")
            n, sample = count_items(body)
            return {"url": u, "status": r.status, "items": n, "sample": sample}
    except urllib.error.HTTPError as e:
        return {"url": u, "status": e.code, "items": 0, "err": "HTTP %s" % e.code}
    except Exception as e:
        return {"url": u, "status": -1, "items": 0, "err": str(e)[:60]}


def probe_host(h):
    key, host, site = h
    tries = []
    best = None
    for u in param_urls(host, site):
        r = probe(u)
        tries.append(r)
        if r.get("items", 0) > 0 and best is None:
            best = r
        time.sleep(0.3)
    return {"key": key, "host": host, "ok": best is not None,
            "feed_url": best["url"] if best else "",
            "items": best["items"] if best else 0,
            "sample": best.get("sample", "") if best else "",
            "tries": tries}


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(probe_host, h) for h in HOSTS]
        for fu in as_completed(futs):
            r = fu.result()
            results.append(r)
            print(("OK  %-9s %3d条 %s" % (r["key"], r["items"], r["feed_url"]))
                  if r["ok"] else ("失  %-9s %s" % (r["key"], [(t["status"], t["items"]) for t in r["tries"]])))
    order = {h[0]: i for i, h in enumerate(HOSTS)}
    results.sort(key=lambda r: order[r["key"]])
    ok = [r for r in results if r["ok"]]
    json.dump({"probed_at": datetime.datetime.utcnow().isoformat() + "Z",
               "ok_count": len(ok), "results": results},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n可用 %d/%d，写 %s" % (len(ok), len(results), OUT))


if __name__ == "__main__":
    main()
