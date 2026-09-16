#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国际涉华公开新闻舆情聚合（GitHub Actions 无人值守，经 Jina 在美国节点读取公开网页）。

两路：
  1) sections  媒体栏目/首页 -> r.jina.ai(Markdown) 提取最新文章链接（主力，便宜、最新）
  2) topics    s.jina.ai 议题检索(after:近N天) -> 补充覆盖面（仅 UTC 0/12 点跑）
只保留近 INTEL_DAYS 天、与议题相关、未入库的文章，r.jina.ai 取正文并清洗，
累积写入 data/intel_feed.json（按 URL 幂等去重，最新在前）。
"""
import os, re, json, ssl, time, hashlib, datetime, urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
FEED = os.path.join(DATA, "intel_feed.json")
SRC = os.path.join(ROOT, "targets", "intel_sources.json")
KEY = os.environ.get("JINA_KEY", "").strip()
DAYS = int(os.environ.get("INTEL_DAYS", "3"))
MAX_ART = int(os.environ.get("INTEL_MAX_ART", "40"))
NUM = os.environ.get("INTEL_SEARCH_NUM", "3")
MAX_FEED = int(os.environ.get("INTEL_MAX_FEED", "600"))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def http(url, accept, timeout=120):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}",
                                               "Accept": accept, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read().decode("utf-8", "ignore"), dict(r.headers)


def reader(target_url, accept="text/plain"):
    try:
        st, body, hdr = http("https://r.jina.ai/" + target_url, accept)
        return st, body, hdr.get("x-usage-tokens", "?")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200], "?"
    except Exception as e:
        return None, "EXC " + repr(e)[:160], "?"


def search(query, after, num=NUM):
    q = urllib.parse.quote(f"{query} after:{after}")
    try:
        st, body, hdr = http(f"https://s.jina.ai/{q}?num={num}", "application/json", timeout=90)
        return json.loads(body).get("data", []) or [], hdr.get("x-usage-tokens", "?")
    except urllib.error.HTTPError as e:
        print(f"[search] HTTP {e.code} {query[:40]}", flush=True)
        return [], "?"
    except Exception as e:
        print(f"[search] fail {query[:40]} {str(e)[:100]}", flush=True)
        return [], "?"


def norm(base, u):
    """把 Markdown 里各种形态的链接归一为绝对 URL（补协议/根路径）。"""
    u = (u or "").strip()
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return "https:" + u
    if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", u):  # 域名开头但缺协议，如 voachinese.com/a/x
        if u.startswith("reuters.com/"):
            u = "www." + u  # 路透无 www 会取空正文
        return "https://" + u
    if u.startswith("/"):
        p = urllib.parse.urlparse(base)
        return f"{p.scheme}://{p.netloc}{u}"
    return urllib.parse.urljoin(base, u)


# ---------- 日期 ----------
def pick_date(*texts):
    for t in texts:
        if not t:
            continue
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", t)
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", t)  # 中文日期
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", t)  # VOA 连续 8 位
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
    return None


def _date(y, mo, d):
    try:
        return datetime.date(int(y), int(mo), int(d))
    except Exception:
        return None


def fresh(dt):
    return dt is not None and (datetime.datetime.utcnow().date() - dt).days <= DAYS and \
        (datetime.datetime.utcnow().date() - dt).days >= -1


# ---------- 正文清洗 ----------
_MENU = re.compile(r"^\s*\*?\*?\s*\[.{0,32}\]\(https?://[^)]*\)\s*$")
_NOISE = ("Powered by", "Print Options", "无障碍", "跳转到", "下一页", "上一页",
          "Google Translate", "translate.google", "此图片内容敏感", "点击显示", "Markdown Content",
          "URL Source:", "请稍等", "player-spinner")


def clean_article(md):
    mt = re.search(r"^Title:\s*(.+)$", md, re.M)
    mp = re.search(r"^Published Time:\s*(.+)$", md, re.M)
    title = mt.group(1).strip() if mt else ""
    pub = mp.group(1).strip() if mp else ""
    body = md.split("Markdown Content:", 1)[-1]
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        if s.startswith("!["):
            continue
        if _MENU.match(s) and len(s) < 80:
            continue
        if any(k in s for k in _NOISE):
            continue
        lines.append(ln.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return title, pub, text[:12000]


def load_feed():
    if os.path.exists(FEED):
        try:
            return json.load(open(FEED, encoding="utf-8"))
        except Exception:
            return []
    return []


def main():
    if not KEY:
        print("[intel] 未配置 JINA_KEY，跳过"); return
    os.makedirs(DATA, exist_ok=True)
    cfg = json.load(open(SRC, encoding="utf-8"))
    sections, topics = cfg["sections"], cfg["search_categories"]
    block = tuple(cfg.get("block_domains", []))
    rel = re.compile(cfg.get("relevance_re", "."))
    after = (datetime.datetime.utcnow().date() - datetime.timedelta(days=DAYS)).isoformat()
    hour = datetime.datetime.utcnow().hour

    feed = load_feed()
    seen = {x["url"] for x in feed}
    candidates = {}  # url -> dict(url, source, lang, cat, hint_date, hint_title)

    def add(url, source, lang, cat, via, hint_date=None, hint_title=""):
        if not url or url in seen or url in candidates:
            return
        if any(b in url.lower() for b in block):
            return
        candidates[url] = {"url": url, "source": source, "lang": lang, "cat": cat, "via": via,
                           "hint_date": hint_date, "hint_title": hint_title}

    # 1) 栏目/首页轮询
    for sec in sections:
        st, body, tok = reader(sec["url"])
        if st != 200:
            print(f"[section] {sec['name']} HTTP {st}", flush=True); continue
        links = []
        for u in re.findall(sec["pat"], body):
            u = norm(sec["url"], u)
            if u not in links:
                links.append(u)
        kept = 0
        for u in links:
            d = pick_date(u)
            if d is None or fresh(d):  # URL 带日期且在窗口内；无日期的留给正文 Published Time 判定
                add(u, sec["name"], sec.get("lang", "?"), sec["cat"], "section", hint_date=d)
                kept += 1
        print(f"[section] {sec['name']}: 链接{len(links)} 候选{kept} tokens={tok}", flush=True)
        time.sleep(0.5)

    # 2) 议题检索（定时仅 UTC 0/12 点；手动触发强制跑，便于验收）
    if hour in (0, 12) or os.environ.get("INTEL_FORCE_SEARCH"):
        for tp in topics:
            items, tok = search(tp["q"], after)
            n = 0
            for it in items:
                u = it.get("url", "")
                blob = " ".join([it.get("title", ""), it.get("description", ""), it.get("content", "")])
                d = pick_date(it.get("date", ""), it.get("publishedTime", ""), u)
                if not rel.search(blob):
                    continue
                if d and not fresh(d):
                    continue
                add(u, tp["cat"], "en", tp["cat"], "topic", hint_date=d, hint_title=it.get("title", ""))
                n += 1
            print(f"[topic] {tp['cat']}: 采纳{n} tokens={tok}", flush=True)
            time.sleep(0.4)
    else:
        print(f"[topic] UTC {hour} 点本轮不跑议题检索（每天 UTC 0/12 点各一次）", flush=True)

    # 3) 抓正文（按日期新->旧，限量控成本；逐项记录丢弃原因）
    cand = list(candidates.values())
    cand.sort(key=lambda x: x["hint_date"] or datetime.date(2000, 1, 1), reverse=True)
    today = datetime.datetime.utcnow().date()
    stats = {"fetch_fail": 0, "no_date": 0, "not_fresh": 0, "too_short": 0, "not_rel": 0}
    added = 0
    for c in cand[:MAX_ART]:
        st, md, tok = reader(c["url"])
        if st != 200 or not md or md.startswith("EXC"):
            stats["fetch_fail"] += 1
            print(f"  x 抓取失败 HTTP{st} {c['url'][:70]}", flush=True)
            continue
        title, pub, text = clean_article(md)
        d = c["hint_date"] or pick_date(pub, c["url"], md[:4000])
        inferred = False
        if not fresh(d):
            if d is None and c["via"] == "section" and os.environ.get("INTEL_TRUST_FRESH", "1") == "1" and len(text) >= 400:
                d, inferred = today, True  # 栏目首页本身即最新流，无日期正文按当天计
            else:
                stats["no_date" if d is None else "not_fresh"] += 1
                continue
        if len(text) < 400:  # 正文过短视为导航页/付费墙/失败
            stats["too_short"] += 1
            print(f"  x 正文过短({len(text)}) {c['url'][:70]}", flush=True)
            continue
        if not rel.search(title + " " + text[:800]):
            stats["not_rel"] += 1
            print(f"  x 不相关 {(title or c['url'])[:50]}", flush=True)
            continue
        item = {
            "id": hashlib.sha1(c["url"].encode()).hexdigest()[:16],
            "title": (title or c["hint_title"] or "(无标题)").strip()[:200],
            "url": c["url"], "source": c["source"], "lang": c["lang"], "cat": c["cat"],
            "published": d.isoformat(), "date_inferred": inferred,
            "fetched_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "summary": re.sub(r"\s+", " ", text)[:240],
            "content": text,
        }
        feed.insert(0, item); seen.add(c["url"]); added += 1
        print(f"  + [{c['cat']}] {item['title'][:46]} ({item['published']}{'?' if inferred else ''}) 正文{len(text)}字 tokens={tok}", flush=True)
        time.sleep(0.4)
    print(f"[intel] 丢弃统计: {stats}", flush=True)

    feed.sort(key=lambda x: x.get("published", ""), reverse=True)
    feed = feed[:MAX_FEED]
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[intel] 本轮新增 {added}，feed 累计 {len(feed)}（近{DAYS}天窗口，每轮正文上限{MAX_ART}）")
    print("INTEL_DONE")


if __name__ == "__main__":
    main()
