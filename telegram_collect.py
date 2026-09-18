#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 公开频道监测（GitHub Actions 美国节点，免登录，只读 t.me/s/<name> 公开网页预览）。

合规红线（代码层面强制）：
  1) 仅访问公开频道网页预览，不登录、不加入、不使用账号/MTProto/Bot API，不碰任何非公开群组；
  2) 图片/视频/语音/文件一律不下载，只记录 has_media / media_types 与公开永久链接；
  3) sensitive=true 类别（暴恐极端/分裂/间谍/组织资金/军品等）命中后只保留短线索
     （标题+前 lead_chars 字摘要+永久链接），usable=false、needs_deepdive=true，不留存正文/媒体本体；
  4) 仅命中 12 类风险词且涉华（或纯中文风险文本）才入库，广告/拉群/博彩/空投等垃圾直接丢弃；
  5) 产物并入 intel_feed.json / intel_brief.json（route=telegram），写稿管线零改动即可使用。
直连优先（零 token），失败用 r.jina.ai 境外代抓兜底。
"""
import os, re, json, ssl, time, html, hashlib, datetime, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
FEED = os.path.join(DATA, "intel_feed.json")
BRIEF = os.path.join(DATA, "intel_brief.json")
TGFILE = os.path.join(DATA, "telegram_feed.json")
CFG = os.path.join(ROOT, "targets", "telegram.json")
KEY = os.environ.get("JINA_KEY", "").strip()
MAX_FEED = int(os.environ.get("INTEL_MAX_FEED", "800"))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_ORG = re.compile(r"(?i)(部|委|局|署|院|府|军|党|盟|会|组织|联盟|阵线|政府|警方|法院|国安|情报|使馆|"
                  r"ministry|government|congress|parliament|council|nato|pentagon|embassy|agency|coalition)")


def get(url, headers=None, timeout=45):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:
        return None, "EXC " + repr(e)[:160]


def strip_html(t):
    if not t:
        return ""
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[ \t]+", " ", html.unescape(t)).strip()


def cjk_ratio(t):
    c = len(re.findall(r"[\u4e00-\u9fff]", t))
    return c / max(len(t), 1)


def lang_of(t):
    r = cjk_ratio(t)
    if r >= 0.5:
        return "zh"
    if r >= 0.12:
        return "mix"
    return "en"


def trigrams(s):
    s = re.sub(r"\s+", "", s)[:320]
    return set(s[i:i + 3] for i in range(len(s) - 2))


def is_dup(text, existing):
    t = trigrams(text)
    if len(t) < 20:
        return False
    for g in existing:
        u = len(t | g)
        if u and len(t & g) / u >= 0.6:
            return True
    return False


def parse_widgets(body, ch):
    """从公开网页 HTML 切出每条消息：id/datetime/文本/媒体标记/转发。"""
    out = []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'data-post="' + re.escape(ch) + r'/(\d+)"', body)]
    for i, (pos, pid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        seg = body[pos:end]
        dm = re.search(r'datetime="(20\d\d-\d\d-\d\d)T([^"]+)"', seg)
        pub = dm.group(1) if dm else ""
        tm = re.search(r'tgme_widget_message_text[^>]*>(.*?)(?:<div class="tgme_widget_message_(?:footer|reply|info))',
                       seg, re.S)
        if not tm:
            tm = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', seg, re.S)
        text = strip_html(tm.group(1)) if tm else ""
        media = []
        if "tgme_widget_message_photo_wrap" in seg:
            media.append("photo")
        if re.search(r"tgme_widget_message_(?:media_video|round_video)", seg):
            media.append("video")
        if "tgme_widget_message_document" in seg:
            media.append("document")
        if re.search(r"tgme_widget_message_(?:voice|audio)", seg):
            media.append("audio")
        fwd = "tgme_widget_message_forwarded_from" in seg
        out.append({"id": pid, "pub": pub, "text": text, "media": media, "fwd": fwd})
    return out


def fetch_direct(ch, days, max_pages, max_n):
    posts, seen_ids, before = [], set(), None
    for _ in range(max_pages):
        url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
        st, body = get(url)
        if st != 200:
            return posts, st
        batch = parse_widgets(body, ch)
        if not batch:
            break
        new = [p for p in batch if p["id"] not in seen_ids]
        for p in new:
            seen_ids.add(p["id"])
        posts.extend(new)
        oldest = min(int(p["id"]) for p in batch)
        # 时间窗：首页带精确日期，早于窗口即停
        cutoff = (datetime.datetime.utcnow().date() - datetime.timedelta(days=days)).isoformat()
        dated = [p["pub"] for p in batch if p["pub"]]
        if dated and min(dated) < cutoff:
            break
        if before == str(oldest) or len(posts) >= max_n:
            break
        before = str(oldest)
        time.sleep(0.4)
    return posts[:max_n], 200


def fetch_jina(ch, days):
    """兜底：Jina markdown 按永久链接切分；时间缺失标 inferred。"""
    st, body = get(f"https://r.jina.ai/https://t.me/s/{ch}",
                   headers={"Authorization": f"Bearer {KEY}", "Accept": "text/plain"}, timeout=90)
    if st != 200:
        return [], st
    out, parts = [], re.split(r"(https?://t\.me/" + re.escape(ch) + r"/\d+[^\s)]*)", body)
    # parts: 前文, link1, text1, link2, text2 ...
    for i in range(1, len(parts) - 1, 2):
        link, txt = parts[i], parts[i + 1]
        pid_m = re.search(r"/(\d+)", link)
        text = strip_html(txt)[:1500]
        if len(text) < 25:
            continue
        out.append({"id": pid_m.group(1) if pid_m else hashlib.sha1(link.encode()).hexdigest()[:10],
                    "pub": "", "text": text, "media": [], "fwd": False, "via": "jina"})
    return out, 200


def score_text(text, cat_hits, china):
    n = len(text)
    sc = 0
    sc += 18 if 120 <= n <= 600 else 15 if 60 <= n < 120 else 13 if 600 < n <= 1200 else 7 if n >= 40 else 2
    if china:
        sc += min(18, 6 + china * 4)
    sc += min(20, cat_hits * 6)
    sc += min(len(re.findall(r"\d", text)) // 4, 8)
    sc += min(len(_ORG.findall(text)) * 3, 9)
    if re.search(r"(https?://|t\.me/|@\w{4,})", text):
        sc += 4
    emo = text.count("!") + text.count("！") + text.count("?") + text.count("？")
    if n and emo / (n / 100) > 6:
        sc -= 8
    if re.search(r"(?i)\b[A-Z]{6,}\b", text) and cjk_ratio(text) < 0.2:
        sc -= 4
    return max(0, min(100, sc))


def main():
    cfg = json.load(open(CFG, encoding="utf-8"))
    days = cfg.get("days", 3); max_pages = cfg.get("max_pages", 2)
    max_n = cfg.get("max_per_channel", 40); qmin = cfg.get("quality_min", 55)
    lead_chars = cfg.get("lead_chars", 180)
    china_re = re.compile(cfg["china_re"])
    junk_re = re.compile("|".join(re.escape(x) for x in cfg["junk_markers"]), re.I)
    cats = []
    for c in cfg["categories"]:
        cats.append({"key": c["key"], "name": c["name"], "sensitive": c["sensitive"],
                     "re": re.compile("|".join(re.escape(k) for k in c["keywords"]), re.I)})
    channels = [(c["name"], c.get("alias", c["name"]), True) for c in cfg.get("selftest_channels", [])]
    channels += [(c, c, False) if isinstance(c, str) else (c["name"], c.get("alias", c["name"]), c.get("selftest", False))
                 for c in cfg.get("business_channels", [])]

    os.makedirs(DATA, exist_ok=True)
    feed = json.load(open(FEED, encoding="utf-8")) if os.path.exists(FEED) else []
    seen = {x["url"] for x in feed}
    existing = [trigrams(x.get("content", "")) for x in feed]
    tg_items, stats = [], {"channels": 0, "scanned": 0, "junk": 0, "not_china": 0, "lead": 0,
                           "usable": 0, "dup": 0, "low": 0, "fail": 0}

    for ch, alias, is_test in channels:
        posts, st = fetch_direct(ch, days, max_pages, max_n)
        via = "direct"
        if not posts:
            posts2, st2 = fetch_jina(ch, days)
            if posts2:
                posts, via, st = posts2, "jina", st2
        if not posts:
            stats["fail"] += 1
            print(f"[tg] {ch}: 抓取失败/0条 HTTP{st}", flush=True)
            continue
        stats["channels"] += 1
        kept = 0
        for p in posts:
            text = (p.get("text") or "").strip()
            stats["scanned"] += 1
            if len(text) < 30:
                continue
            if junk_re.search(text):
                stats["junk"] += 1; continue
            hit = next((c for c in cats if c["re"].search(text)), None)
            china_n = len(china_re.findall(text))
            china = china_n > 0 or cjk_ratio(text) >= 0.5
            if not hit:
                continue
            if not china:
                stats["not_china"] += 1; continue
            url = f"https://t.me/{ch}/{p['id']}"
            if url in seen:
                continue
            if is_dup(text, existing):
                stats["dup"] += 1; continue
            cat_hits = len(hit["re"].findall(text))
            sc = score_text(text, cat_hits, china_n)
            sensitive = hit["sensitive"]
            today = datetime.datetime.utcnow().date().isoformat()
            inferred = not p.get("pub")
            published = p.get("pub") or today
            first = re.split(r"[。.!?！？\n]", text)[0][:40] or text[:40]
            item = {
                "id": hashlib.sha1(url.encode()).hexdigest()[:16],
                "title": ("【线索】" if sensitive else "") + first.strip(),
                "url": url, "source": alias, "lang": lang_of(text), "cat": hit["name"],
                "route": "telegram", "body_from": "lead" if sensitive else ("jina" if via == "jina" else "full"),
                "quality_score": min(sc, 48) if sensitive else sc,
                "usable": (not sensitive) and sc >= qmin,
                "needs_deepdive": bool(sensitive or via == "jina"),
                "published": published, "date_inferred": inferred,
                "fetched_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "summary": re.sub(r"\s+", " ", text)[:240],
                "content": text[:lead_chars] if sensitive else text[:4000],
                "has_media": bool(p.get("media")), "media_types": p.get("media", []),
                "forwarded": bool(p.get("fwd")), "category_key": hit["key"],
            }
            if sensitive:
                item["handling"] = "高敏类别仅留公开线索，未下载/留存正文与媒体本体，按程序报专门机关核查"
                stats["lead"] += 1
            elif item["usable"]:
                stats["usable"] += 1
            else:
                stats["low"] += 1
            feed.insert(0, item); tg_items.append(item); seen.add(url)
            existing.append(trigrams(item["content"])); kept += 1
            tag = "线索" if sensitive else ("可用" if item["usable"] else "存档")
            print(f"  +[{tag}|{item['quality_score']}|{hit['name'][:10]}] {alias} {item['title'][:34]} "
                  f"({published}{'?' if inferred else ''}) media={item['media_types']}", flush=True)
        print(f"[tg] {alias}: 消息{len(posts)} 入库{kept} via={via}", flush=True)
        time.sleep(0.5)

    feed.sort(key=lambda x: x.get("published", ""), reverse=True)
    feed = feed[:MAX_FEED]
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    brief = sorted([x for x in feed if x.get("usable")],
                   key=lambda x: (x.get("quality_score", 0), x.get("published", "")), reverse=True)
    json.dump(brief, open(BRIEF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(tg_items, open(TGFILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[tg] 统计 {stats}", flush=True)
    print(f"[tg] 本轮 Telegram 入库 {len(tg_items)}（高敏线索 {stats['lead']}、可研判 {stats['usable']}）；"
          f"feed 累计 {len(feed)}，brief {len(brief)}", flush=True)
    print("TG_DONE")


if __name__ == "__main__":
    main()
