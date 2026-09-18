#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：dump 若干无日期 feed 的原始 item 结构（美国节点直连）。结果写 data/feeddiag.json。"""
import os, re, ssl, json, urllib.request, urllib.error
import xml.etree.ElementTree as ET
ROOT = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HOSTS = ["thediplomat.com", "csis.org", "merics.org", "hongkongfp.com", "bellingcat.com",
         "voachinese.com", "jamestown.org", "cato.org", "ecfr.eu", "aiddata.org",
         "thewirechina.com", "selectcommitteeontheccp.house.gov", "foreignaffairs.com", "aspi.org.au"]


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "EXC " + type(e).__name__


def ln(t):
    return t.split("}")[-1].lower()


probe = json.load(open(os.path.join(ROOT, "data", "institute_probe.json"), encoding="utf-8"))
by = {x["host"]: x for x in probe}
out = []
for h in HOSTS:
    x = by.get(h)
    if not x or not x.get("feed_url"):
        out.append({"host": h, "error": "no feed_url"}); continue
    st, body = get(x["feed_url"])
    rec = {"host": h, "http": st, "feed_url": x["feed_url"], "head": body[:120].replace("\n", " ")}
    try:
        root = ET.fromstring(body)
        rec["root"] = ln(root.tag)
        items = [e for e in root.iter() if ln(e.tag) in ("item", "entry")]
        rec["n_items"] = len(items)
        if items:
            it = items[0]
            rec["children"] = [ln(c.tag) for c in it]
            rec["date_like"] = {}
            for c in it:
                if any(k in ln(c.tag) for k in ("date", "time", "pub", "updated", "issued", "created")):
                    rec["date_like"][ln(c.tag)] = (c.text or "")[:60]
            rec["raw"] = ET.tostring(it, encoding="unicode")[:900]
    except Exception as e:
        rec["parse_error"] = repr(e)[:200]
    out.append(rec)
json.dump(out, open(os.path.join(ROOT, "data", "feeddiag.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("FEEDDIAG_DONE", len(out))
