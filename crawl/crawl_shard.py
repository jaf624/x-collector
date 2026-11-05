# -*- coding: utf-8 -*-
"""采集分片工人 v2：在 GitHub Actions（有外网）上跑。
  1) 拉源清单 → RSS/首页取条目
  2) 顺手抓正文（纯代码启发式，不用模型）→ 正文≥400 字的才算合格
  3) 每片最多抓 BODY_MAX 篇正文，避免单 job 超时
输出：out/crawl_<shard>.json
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; intelhub-swarm/1.0)"}
BODY_MIN = 400
BODY_MAX = 36


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


_DROP = re.compile(r"<(script|style|nav|header|footer|aside|form|iframe)[^>]*>.*?</\1>", re.S | re.I)
_NOISE = re.compile(r"(责任编辑|版权所有|Copyright|cookie|Cookie|隐私政策|登录|注册|扫一扫|扫码|下载APP|关注我们|订阅)")


def extract_body(html_text):
    """纯代码抽正文：去脚本/导航，取最长的一段连续 <p> 文本"""
    t = _DROP.sub(" ", html_text)
    ps = re.findall(r"<p[^>]*>(.*?)</p>", t, re.S | re.I)
    cand = []
    for p in ps:
        s = re.sub(r"<[^>]+>", "", p)
        s = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 25 and not _NOISE.search(s):
            cand.append(s)
    body = "".join(cand)
    if len(body) < BODY_MIN:  # p 不够，退化取整页可见文本
        s = re.sub(r"<[^>]+>", " ", t)
        s = re.sub(r"\s+", " ", s).strip()
        body = s if len(s) > len(body) else body
    return body


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
    ap.add_argument("--body-max", type=int, default=BODY_MAX)
    ap.add_argument("--sources", default="")
    ap.add_argument("--sources-url", default="")
    ap.add_argument("--out", default="out/crawl.json")
    a = ap.parse_args()

    srcs = json.loads(get(a.sources_url)) if a.sources_url else json.load(open(a.sources, encoding="utf-8"))
    mine = [s for i, s in enumerate(srcs) if i % a.total == a.shard][:a.n]

    rows = []
    stats = {"src_tried": 0, "src_ok": 0, "items": 0, "body_tried": 0, "body_ok": 0}
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
            print("SKIP %s %s" % (payload[:60], str(e)[:50]))

    # 正文抓取：只对前 body-max 条做，抓不到标 title_only
    picked = rows[:a.body_max]
    for it in picked:
        stats["body_tried"] += 1
        try:
            html_text = get(it["url"], timeout=15)
            body = extract_body(html_text)
            it["body"] = body[:8000]
            it["body_len"] = len(body)
            if len(body) >= BODY_MIN:
                stats["body_ok"] += 1
                it["title_only"] = 0
            else:
                it["title_only"] = 1
        except Exception as e:
            it["body"] = ""
            it["body_len"] = 0
            it["title_only"] = 1
            print("BODY-SKIP %s %s" % (it["url"][:60], str(e)[:40]))
        time.sleep(0.3)

    # 有正文的排前面，方便服务器先吃好的
    picked.sort(key=lambda x: -int(x.get("body_len") or 0))
    keep = [x for x in picked if (x.get("body_len") or 0) >= BODY_MIN]
    stats["items"] = len(keep)
    out = {"shard": a.shard, "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "stats": stats, "rows": keep}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
