#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 公开频道监测（GitHub Actions 美国节点，免登录，只读 t.me/s/<name> 公开网页预览）。

合规红线（代码层面强制）：
  1) 仅访问业务配置的公开频道网页预览，不登录、不加入、不使用账号/MTProto/Bot API，不碰非公开群组；
  2) 图片/视频/语音/文件一律不下载，只记录 has_media / media_types 与公开永久链接；
  3) sensitive=true 类别（暴恐极端/分裂/间谍/组织资金/军品等）命中后只保留短线索
     （标题+前 lead_chars 字摘要+永久链接），usable=false、needs_deepdive=true，不留存正文/媒体本体；
  4) 仅命中 12 类风险词且涉华（或纯中文风险文本）才入库，广告/拉群/博彩/空投等垃圾直接丢弃；
  5) 产物并入 intel_feed.json / intel_brief.json（route=telegram），写稿管线零改动即可使用。
直连优先（零 token），失败用 r.jina.ai 境外代抓兜底。连通性自测由 telegram_selftest.py 独立负责，
本脚本不抓取自测中性频道，避免污染情报库。
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


def build_re(words):
    """中文按词子串；英文短语加字母边界并忽略大小写；全大写缩写(<=6字母)加边界且大小写敏感。
    避免 NED 命中 signed、PLA 命中 plain、APT 命中 adapt、NDI 命中 candidate 之类短词误报。"""
    zh, ci, cs = [], [], []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if re.search(r"[\u4e00-\u9fff]", w):
            zh.append(re.escape(w)); continue
        b = r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])"
        letters = "".join(c for c in w if c.isalpha())
        if letters and letters == letters.upper() and len(letters) <= 6:
            cs.append(b)
        else:
            ci.append(b)
    pcs = []
    if zh or ci:
        pcs.append("(?:" + "|".join(zh + ci) + ")")
    if cs:
        pcs.append("(?-i:" + "|".join(cs) + ")")
    return re.compile("|".join(pcs), re.I)


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
    return len(re.findall(r"[\u4e00-\u9fff]", t)) / max(len(t), 1)


def lang_of(t):
    r = cjk_ratio(t)
    return "zh" if r >= 0.5 else ("mix" if r >= 0.12 else "en")


_PROMO = re.compile(r"(?i)(订阅|訂閱|发电邮|發電郵|电邮|電郵|邮箱|郵箱|聯絡|联络|联系我们|聯繫我們|投稿|广告合作|联系客服|点此|關注我們|关注我们|加入频道|promotion|subscribe|newsletter|advertis|contact via|join\s*here)")


def clean_title(text):
    """去链接/邮箱/@与推广套话后，取第一个有信息量(>=8字且非推广)的句子作标题。"""
    t = re.sub(r"https?://\S+|t\.me/\S+|[\w.\-]+@[\w.\-]+|@\w+", "", text)
    for s in re.split(r"[。.!?！？\n|]", t):
        s = s.strip(" ，,、:：;；-—~～")
        if len(re.sub(r"\s", "", s)) >= 8 and not _PROMO.search(s):
            return s[:40]
    return re.sub(r"\s+", " ", t).strip()[:40]


def informative_len(text):
    t = re.sub(r"https?://\S+|t\.me/\S+|[\w.\-]+@[\w.\-]+|@\w+", "", text)
    return len(re.sub(r"\s", "", t))


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
    out = []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'data-post="' + re.escape(ch) + r'/(\d+)"', body)]
    for i, (pos, pid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        seg = body[pos:end]
        dm = re.search(r'datetime="(20\d\d-\d\d-\d\d)T([^"]+)"', seg)
        tm = re.search(r"tgme_widget_message_text[^>]*>(.*?)(?:<div class=\"tgme_widget_message_(?:footer|reply|info))",
                       seg, re.S) or re.search(r"tgme_widget_message_text[^>]*>(.*?)</div>", seg, re.S)
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
        out.append({"id": pid, "pub": dm.group(1) if dm else "", "text": text,
                    "media": media, "fwd": "tgme_widget_message_forwarded_from" in seg})
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
        for p in batch:
            if p["id"] not in seen_ids:
                seen_ids.add(p["id"]); posts.append(p)
        oldest = min(int(p["id"]) for p in batch)
        cutoff = (datetime.datetime.utcnow().date() - datetime.timedelta(days=days)).isoformat()
        dated = [p["pub"] for p in batch if p["pub"]]
        if dated and min(dated) < cutoff:
            break
        if before == str(oldest) or len(posts) >= max_n:
            break
        before = str(oldest); time.sleep(0.4)
    return posts[:max_n], 200


def fetch_jina(ch):
    st, body = get(f"https://r.jina.ai/https://t.me/s/{ch}",
                   headers={"Authorization": f"Bearer {KEY}", "Accept": "text/plain"}, timeout=90)
    if st != 200:
        return [], st
    out, parts = [], re.split(r"(https?://t\.me/" + re.escape(ch) + r"/\d+[^\s)]*)", body)
    for i in range(1, len(parts) - 1, 2):
        link, txt = parts[i], parts[i + 1]
        pid_m = re.search(r"/(\d+)", link)
        text = strip_html(txt)[:1500]
        if len(text) >= 25:
            out.append({"id": pid_m.group(1) if pid_m else hashlib.sha1(link.encode()).hexdigest()[:10],
                        "pub": "", "text": text, "media": [], "fwd": False})
    return out, 200


def score_text(text, cat_hits, china_n):
    n = len(text)
    sc = 18 if 120 <= n <= 600 else 17 if 60 <= n < 120 else 13 if 600 < n <= 1200 else 7 if n >= 40 else 2
    if china_n:
        sc += min(18, 6 + china_n * 4)
    sc += min(22, cat_hits * 6)
    sc += min(len(re.findall(r"\d", text)) // 4, 8)
    sc += min(len(_ORG.findall(text)) * 3, 9)
    if re.search(r"(https?://|t\.me/|@\w{4,})", text):
        sc += 4
    emo = text.count("!") + text.count("！") + text.count("?") + text.count("？")
    if n and emo / (n / 100) > 6:
        sc -= 8
    if re.search(r"\b[A-Z]{6,}\b", text) and cjk_ratio(text) < 0.2:
        sc -= 4
    return max(0, min(100, sc))


def main():
    cfg = json.load(open(CFG, encoding="utf-8"))
    days = cfg.get("days", 3); max_pages = cfg.get("max_pages", 2)
    max_n = cfg.get("max_per_channel", 40); qmin = cfg.get("quality_min", 50)
    lead_chars = cfg.get("lead_chars", 180)
    china_re = build_re(cfg["china_keywords"])
    junk_re = build_re(cfg["junk_markers"])
    cats = [{"key": c["key"], "name": c["name"], "sensitive": c["sensitive"], "re": build_re(c["keywords"])}
            for c in cfg["categories"]]
    channels = [(c, c) if isinstance(c, str) else (c["name"], c.get("alias", c["name"]))
                for c in cfg.get("business_channels", [])]

    os.makedirs(DATA, exist_ok=True)
    feed = json.load(open(FEED, encoding="utf-8")) if os.path.exists(FEED) else []
    before_n = len(feed)
    feed = [x for x in feed if not (x.get("route") == "telegram"
             and ("自测" in x.get("source", "") or "官方公告" in x.get("source", "")))]
    if len(feed) != before_n:
        print(f"[tg] 已清除自测频道误报 {before_n - len(feed)} 条", flush=True)

    if not channels:
        json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        brief = sorted([x for x in feed if x.get("usable")],
                       key=lambda x: (x.get("quality_score", 0), x.get("published", "")), reverse=True)
        json.dump(brief, open(BRIEF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump([], open(TGFILE, "w", encoding="utf-8"), ensure_ascii=False)
        print("[tg] 未配置业务公开频道(business_channels 为空)，本轮跳过抓取、零入库；TG_DONE", flush=True)
        return

    biz_names = {ch for ch, _ in channels}

    def _in_biz(x):
        m = re.match(r"https?://t\.me/([^/]+)/", x.get("url", ""))
        return bool(x.get("route") == "telegram" and m and m.group(1) in biz_names)

    bn = len(feed)
    feed = [x for x in feed if not _in_biz(x)]  # 每轮按当前名单全量刷新近窗，淘汰旧帖/改判
    if len(feed) != bn:
        print(f"[tg] 刷新：移除上轮业务频道旧条目 {bn - len(feed)}", flush=True)
    cutoff = (datetime.datetime.utcnow().date() - datetime.timedelta(days=days)).isoformat()
    seen = {x["url"] for x in feed}
    existing = [trigrams(x.get("content", "")) for x in feed]
    tg_items, stats = [], {"channels": 0, "scanned": 0, "junk": 0, "not_china": 0, "lead": 0,
                           "usable": 0, "dup": 0, "low": 0, "expired": 0, "lowinfo": 0, "fail": 0}
    for ch, alias in channels:
        posts, st = fetch_direct(ch, days, max_pages, max_n)
        via = "direct"
        if not posts:
            posts, st2 = fetch_jina(ch)
            if posts:
                via, st = "jina", st2
        if not posts:
            stats["fail"] += 1; print(f"[tg] {ch}: 抓取失败/0条 HTTP{st}", flush=True); continue
        stats["channels"] += 1; kept = 0
        for p in posts:
            text = (p.get("text") or "").strip()
            stats["scanned"] += 1
            if len(text) < 30 or junk_re.search(text):
                stats["junk"] += 1; continue
            if p.get("pub") and p["pub"] < cutoff:
                stats["expired"] += 1; continue
            if informative_len(text) < 25:
                stats["lowinfo"] += 1; continue
            hit = next((c for c in cats if c["re"].search(text)), None)
            china_n = len(china_re.findall(text))
            if not hit:
                continue
            if not (china_n or cjk_ratio(text) >= 0.5):
                stats["not_china"] += 1; continue
            url = f"https://t.me/{ch}/{p['id']}"
            if url in seen or is_dup(text, existing):
                stats["dup"] += 1; continue
            sc = score_text(text, len(hit["re"].findall(text)), china_n)
            sensitive = hit["sensitive"]
            published = p.get("pub") or datetime.datetime.utcnow().date().isoformat()
            first = clean_title(text)
            item = {
                "id": hashlib.sha1(url.encode()).hexdigest()[:16],
                "title": ("【线索】" if sensitive else "") + first.strip(),
                "url": url, "source": alias, "lang": lang_of(text), "cat": hit["name"],
                "route": "telegram", "body_from": "lead" if sensitive else ("jina" if via == "jina" else "full"),
                "quality_score": min(sc, 48) if sensitive else sc,
                "usable": (not sensitive) and sc >= qmin,
                "needs_deepdive": bool(sensitive or via == "jina"),
                "published": published, "date_inferred": not p.get("pub"),
                "fetched_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "summary": re.sub(r"\s+", " ", text)[:240],
                "content": text[:lead_chars] if sensitive else text[:4000],
                "has_media": bool(p.get("media")), "media_types": p.get("media", []),
                "forwarded": bool(p.get("fwd")), "category_key": hit["key"]}
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
                  f"({published}{'?' if item['date_inferred'] else ''}) media={item['media_types']}", flush=True)
        print(f"[tg] {alias}: 消息{len(posts)} 入库{kept} via={via}", flush=True)
        time.sleep(0.5)

    feed.sort(key=lambda x: x.get("published", ""), reverse=True); feed = feed[:MAX_FEED]
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
