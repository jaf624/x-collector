# -*- coding: utf-8 -*-
"""采集分片工人：不依赖服务器，任何有外网的机器都能跑（GitHub Actions 每个 job 跑一片）。
用法：python3 crawl_shard.py --shard 1 --total 8 --n 40 --out out/crawl_1.json
读取源清单：--sources 本地路径 或 --sources-url http://.../sources.json
"""
import argparse
import datetime
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; intelhub-swarm/1.0)"}


def parse_feed(text):
    out = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return out
    for it in root.iter():
        if it.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        title = link = date = desc = ""
        for ch in it:
            t = ch.tag.split("}")[-1].lower()
            if t == "title":
                title = (ch.text or "").strip()
            elif t == "link":
                link = (ch.text or ch.attrib.get("href") or "").strip()
            elif t in ("pubdate", "published", "updated", "date"):
                date = (ch.text or "").strip()[:32]
            elif t in ("description", "summary", "content"):
                desc = re.sub(r"<[^>]+>", "", (ch.text or ""))[:600]
        if title and link.startswith("http"):
            out.append({"title": title, "url": link, "published": date, "summary": desc})
    return out


def parse_html(base, text):
    out = []
    host = urllib.parse.urlparse(base).netloc
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not (12 <= len(label) <= 90):
            continue
        u = urllib.parse.urljoin(base, href)
        if urllib.parse.urlparse(u).netloc != host:
            continue
        if re.search(r"[#?]|/tag/|/category/|/page/|/author/", u):
            continue
        out.append({"title": label, "url": u, "published": "", "summary": ""})
    return out[:50]


def get(url, timeout=20):
    r = requests.get(url, headers=UA, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError("HTTP %d" % r.status_code)
    return r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--total", type=int, default=8)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--sources", default="")
    ap.add_argument("--sources-url", default="")
    ap.add_argument("--out", default="out/crawl.json")
    a = ap.parse_args()

    if a.sources_url:
        srcs = json.loads(get(a.sources_url))
    else:
        srcs = json.load(open(a.sources, encoding="utf-8"))

    # 分片：按源的下标取余，8 个进程互不重叠
    mine = [s for i, s in enumerate(srcs) if i % a.total == a.shard][:a.n]
    rows = []
    stats = {"src_tried": 0, "src_ok": 0, "items": 0}
    for s in mine:
        payload = (s.get("feed_url") or s.get("base") or s.get("ref") or "").strip()
        if not payload.startswith("http"):
            continue
        stats["src_tried"] += 1
        try:
            txt = get(payload)
            items = parse_feed(txt) or parse_html(payload, txt)
            if not items:
                continue
            stats["src_ok"] += 1
            for it in items[:60]:
                it["source"] = (s.get("name") or s.get("host") or "")[:60]
                it["host"] = (s.get("host") or "")[:80]
                rows.append(it)
        except Exception as e:
            rows and None
            print("SKIP %s %s" % (payload[:60], str(e)[:50]))

    stats["items"] = len(rows)
    out = {"shard": a.shard, "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "stats": stats, "rows": rows}
    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
