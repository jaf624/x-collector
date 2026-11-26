#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google News RSS 题材聚合采集（辅助扩量源，非主力）。
- 定位：发现哪些外媒在同步报道同一事件，补原生RSS漏网
- 主力仍是197个机构原生RSS；本源 quality_score 低，让原生源优先
- 跳转链接resolve到原文直链；超过7天旧闻不收；标题去重
跑在 GitHub Actions（境外 runner），每 2 小时一次。
"""
import os, re, json, time, hashlib, datetime, urllib.request, urllib.parse, ssl, xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(ROOT, "data", "intel_feed.json")
SRC = os.path.join(ROOT, "targets", "intel_sources.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
MAX_AGE_DAYS = 7  # 只收7天内

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不自动跳转，我们自己拿Location

opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        return r.read()
    except Exception as e:
        return b""

def resolve_redirect(gnews_url, timeout=10):
    """Google News 跳转链接 -> 原文直链。拿不到就返回原链接。"""
    try:
        req = urllib.request.Request(gnews_url, headers={"User-Agent": UA})
        r = opener.open(req, timeout=timeout)
        return gnews_url  # 没跳转
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        if loc and "news.google.com" not in loc:
            return loc
        return gnews_url
    except Exception:
        return gnews_url

def parse_pubdate(s):
    try:
        return datetime.datetime.strptime(s[:25], "%a, %d %b %Y %H:%M:%S")
    except Exception:
        return None

TRACK_PARAMS = {"hl", "gl", "ceid", "oc"}

def _aid(u):
    """Google News 文章段 ID；同一文章只是跟踪参数变体时，ID 不变。"""
    m = re.search(r"/articles/([^?/]+)", u or "")
    return m.group(1) if m else ""

def _norm_url(u):
    """去掉 hl/gl/ceid/oc 等跟踪查询参数，避免同文不同链接绕过去重。"""
    u = (u or "").strip()
    if "?" in u:
        base, q = u.split("?", 1)
        keep = [p for p in q.split("&") if p and p.split("=")[0] not in TRACK_PARAMS]
        u = base + ("?" + "&".join(keep) if keep else "")
    return u

def _dedup_gn(feed):
    """存量 gnews 条目按文章 ID（兜底标题）去重，直连源条目不动。"""
    seen_aid, seen_title, out = set(), set(), []
    for x in feed:
        if x.get("route") != "gnews_topic":
            out.append(x)
            continue
        aid = _aid(x.get("url", ""))
        key_t = (x.get("title", "") or "")[:60]
        if aid and aid in seen_aid:
            continue
        if key_t and key_t in seen_title:
            continue
        seen_aid.add(aid); seen_title.add(key_t)
        out.append(x)
    return out

def gnews_search(q, n=5):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    body = fetch(url, 15)
    if not body:
        return []
    out = []
    try:
        root = ET.fromstring(body)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            src_el = item.find("source")
            src = (src_el.text or "").strip() if src_el is not None else "Google News"
            if title and link:
                out.append({"title": title, "url": link, "pub": pub, "src": src})
            if len(out) >= n:
                break
    except Exception:
        pass
    return out

def main():
    cfg = json.load(open(SRC, encoding="utf-8"))
    topics = cfg.get("search_categories", [])
    feed = json.load(open(FEED, encoding="utf-8")) if os.path.exists(FEED) else []
    feed = _dedup_gn(feed)
    existing_aid = set(filter(None, (_aid(x.get("url", "")) for x in feed)))
    existing = set(_norm_url(x.get("url", "")) for x in feed)
    existing_titles = set(x.get("title", "")[:60] for x in feed)
    now = datetime.datetime.utcnow()
    now_iso = now.isoformat()
    cutoff = now - datetime.timedelta(days=MAX_AGE_DAYS)
    added = 0; skipped_old = 0; skipped_dup = 0
    for tp in topics:
        cat = tp.get("cat", "")
        q = tp.get("q", "")
        if not q:
            continue
        for art in gnews_search(q, n=5):
            t = art["title"]
            if len(t) < 12:
                continue
            # 新旧判断
            pd = parse_pubdate(art["pub"])
            if pd and pd < cutoff:
                skipped_old += 1; continue
            aid = _aid(art["url"])
            # 文章 ID 或标题命中即判重，挡住跟踪参数变体
            if (aid and aid in existing_aid) or t[:60] in existing_titles:
                skipped_dup += 1; continue
            orig_url = resolve_redirect(art["url"])
            norm = _norm_url(orig_url)
            if norm in existing:
                skipped_dup += 1; continue
            hid_src = aid or norm
            hid = hashlib.md5(hid_src.encode()).hexdigest()[:16]
            feed.append({
                "id": "gn_" + hid,
                "title": t,
                "url": orig_url,
                "source": "GN聚合·" + art["src"],
                "lang": "en",
                "cat": cat,
                "route": "gnews_topic",
                "summary": "",
                "content": "",
                "published": art["pub"],
                "fetched_at": now_iso,
                "quality_score": 30,  # 低于原生RSS，让一手源优先
                "usable": 0,
                "needs_deepdive": 1,
                "forwarded": 0,
                "category_key": cat,
                "handling": "gnews_aggregator",
            })
            existing_aid.add(aid); existing.add(norm); existing_titles.add(t[:60])
            added += 1
        time.sleep(0.3)
    feed = feed[-3000:]
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False)
    print("GN聚合: 新增%d 旧闻跳过%d 重复跳过%d 总计%d" % (added, skipped_old, skipped_dup, len(feed)))

if __name__ == "__main__":
    main()
