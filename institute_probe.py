#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机构源 RSS/Atom 可达性与涉华相关度探测（GitHub Actions 美国节点，纯直连公开 feed，不登录、不下载正文/附件）。

读 targets/institute_sources.json，对每个源：
  发现 RSS/Atom（feed 自描述 <link> + 常见路径）-> 解析最近条目 -> 统计最新日期/近30天/涉华命中
回写 targets/institute_sources.json（补 status/feed_url/kind/latest/recent30/china_hits），
明细落 data/institute_probe.json。终端只打印计数。
"""
import os, re, ssl, json, time, email.utils, datetime, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
SRC = os.path.join(ROOT, "targets", "institute_sources.json")
INTEL = os.path.join(ROOT, "targets", "intel_sources.json")
OUT = os.path.join(DATA, "institute_probe.json")
MAX_BYTES = int(os.environ.get("INST_PROBE_MAXMB", "2")) * 1024 * 1024
WORKERS = int(os.environ.get("INST_PROBE_WORKERS", "12"))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CAND = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml",
        "/feeds/posts/default", "/news/rss", "/feeds/news.xml", "/news/feed",
        "/publications/rss", "/en/feed", "/zh/feed", "/?feed=rss2"]
LINK_RE = re.compile(r"<link\b[^>]*>", re.I | re.S)
TODAY = datetime.datetime.utcnow().date()
CUT30 = TODAY - datetime.timedelta(days=30)


def get(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read(MAX_BYTES)
            enc = "utf-8"
            ct = r.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ct)
            if m:
                enc = m.group(1)
            return r.status, body.decode(enc, "ignore"), r.geturl(), ct
    except urllib.error.HTTPError as e:
        return e.code, "", url, ""
    except Exception as e:
        return None, f"EXC {type(e).__name__}", url, ""


def looks_feed(ct, body):
    if not body:
        return False
    if "xml" in (ct or "").lower() and ("<rss" in body[:800] or "<feed" in body[:800]):
        return True
    return body.lstrip()[:5] in ("<?xml", "<rss", "<feed") or ("<rss" in body[:800] or "<feed" in body[:800])


def html_feed_links(base, body):
    found = []
    for tag in LINK_RE.findall(body[:200000]):
        if not re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            continue
        m = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if m:
            found.append(urllib.parse.urljoin(base, m.group(1)))
    rank = lambda u: (0 if re.search(r"rss|feed|news|china|/zh", u, re.I) else 1, len(u))
    return sorted(dict.fromkeys(found), key=rank)


def lname(el):
    return el.tag.split("}")[-1].lower()


def child(el, name):
    for c in el:
        if lname(c) == name:
            return c
    return None


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
        return dt.date() if dt else None
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", s)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                return None
    return None


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_feed(body):
    try:
        root = ET.fromstring(body)
    except Exception:
        return []
    nodes = [e for e in root.iter() if lname(e) in ("item", "entry")]
    items = []
    for e in nodes[:80]:
        t = child(e, "title")
        title = strip_html(t.text if t is not None else "")
        link = ""
        for c in e:
            if lname(c) == "link":
                href = c.get("href")
                if href and (not c.get("rel") or c.get("rel") == "alternate"):
                    link = href; break
                if not href and (c.text or "").strip():
                    link = c.text.strip(); break
        dnode = None
        for nm in ("pubdate", "published", "updated", "date", "issued", "created"):
            c = child(e, nm)
            if c is not None and (c.text or "").strip():
                dnode = c
                break
        date = parse_date(dnode.text if dnode is not None else "")
        desc = ""
        for nm in ("encoded", "content", "summary", "description"):
            c = child(e, nm)
            if c is not None and (c.text or "").strip():
                desc = strip_html(c.text)[:600]; break
        items.append({"title": title[:200], "link": link, "date": date, "desc": desc})
    return items


def discover(src):
    ref, base = src.get("ref") or src["base"], src["base"]
    root = urllib.parse.urlparse(base)
    root = f"{root.scheme}://{root.netloc}"
    for start in [ref, base]:
        st, body, final, ct = get(start)
        if st == 200 and body and not body.startswith("EXC"):
            if looks_feed(ct, body):
                return final, "self", body
            for l in html_feed_links(final, body)[:4]:
                st2, b2, f2, ct2 = get(l)
                if st2 == 200 and b2 and looks_feed(ct2, b2):
                    return l, "html_link", b2
            for p in CAND:
                st2, b2, f2, ct2 = get(root + p)
                if st2 == 200 and b2 and looks_feed(ct2, b2):
                    return root + p, "path", b2
            break
    return None, None, None


def probe_one(src, rel):
    feed_url, kind, body = discover(src)
    rec = {"host": src["host"], "name": src["name"], "cat": src["cat"], "mode": src.get("mode", "full"),
           "feed_url": feed_url, "kind": kind, "status": "dead", "total": 0, "latest": None,
           "recent30": 0, "china_hits": 0, "samples": []}
    if not feed_url:
        rec["status"] = "need_jina"
        return rec
    items = parse_feed(body)
    rec["total"] = len(items)
    dates = [it["date"] for it in items if it["date"]]
    if dates:
        rec["latest"] = max(dates).isoformat()
    rec["recent30"] = sum(1 for d in dates if d >= CUT30)
    china = [it for it in items if rel.search(it["title"] + " " + it["desc"])]
    rec["china_hits"] = len(china)
    rec["samples"] = [it["title"] for it in china[:3]] or [it["title"] for it in items[:3]]
    if rec["china_hits"] >= 1 and (rec["recent30"] >= 1 or not dates):
        rec["status"] = "active"
    elif rec["recent30"] >= 1:
        rec["status"] = "watch"
    elif dates:
        rec["status"] = "stale"
    else:
        rec["status"] = "watch"
    return rec


def main():
    os.makedirs(DATA, exist_ok=True)
    srcs = json.load(open(SRC, encoding="utf-8"))
    rel = re.compile(json.load(open(INTEL, encoding="utf-8")).get("relevance_re", "."), re.I)
    results = [None] * len(srcs)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(probe_one, s, rel): i for i, s in enumerate(srcs)}
        done = 0
        for fu in as_completed(futs):
            i = futs[fu]; results[i] = fu.result(); done += 1
            if done % 25 == 0:
                print(f"  ...{done}/{len(srcs)}", flush=True)
    by_host = {r["host"]: r for r in results}
    for s in srcs:
        r = by_host.get(s["host"])
        if r:
            s.update({"feed_url": r["feed_url"], "kind": r["kind"], "status": r["status"],
                      "latest": r["latest"], "recent30": r["recent30"], "china_hits": r["china_hits"]})
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(srcs, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    c = Counter(r["status"] for r in results)
    print("探测源总数:", len(results))
    print("状态计数:", dict(c))
    print("INSTITUTE_PROBE_DONE")


if __name__ == "__main__":
    main()
