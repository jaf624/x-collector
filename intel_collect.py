#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国际涉华公开舆情聚合（GitHub Actions 无人值守，经 Jina 在美国节点读取公开网页）。

三路：
  1) sections  媒体栏目/首页 -> r.jina.ai(Markdown) 提取最新文章链接（每 6 小时，主力、最新）
  2) topics    s.jina.ai 议题新闻检索（每天 UTC0/12，近 INTEL_DAYS 天）
  3) watch     反华人物账号 / 活动事件 / 新路径手法 / 组织新群追踪（每天 UTC0/12，近 INTEL_WATCH_DAYS 天）
       - Reddit / change.org / 新闻报告站：r.jina.ai 取全文
       - Facebook/Instagram/X/YouTube/Telegram 等抓不到正文的壳：只存搜索快照线索，不烧 token、不编造正文
只读取公开网页 / 公开账号 / 公开请愿，不进入任何非公开社群，不参与、不组织任何活动。

质量层：长度 / 事实要素密度 / 结构 / 广告付费墙 / 标题党 / 近重复通稿 确定性打分。
输出两份：
  data/intel_feed.json   过基础门槛的全量（含社媒线索，带 quality_score / usable / body_from）
  data/intel_brief.json  仅 usable=true 的高信息密度稿，供大模型研判 / 写材料（即"过滤后送模型"那一层）
"""
import os, re, json, ssl, time, hashlib, datetime, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
FEED = os.path.join(DATA, "intel_feed.json")
BRIEF = os.path.join(DATA, "intel_brief.json")
SRC = os.path.join(ROOT, "targets", "intel_sources.json")
KEY = os.environ.get("JINA_KEY", "").strip()
DAYS = int(os.environ.get("INTEL_DAYS", "3"))
WATCH_DAYS = int(os.environ.get("INTEL_WATCH_DAYS", "7"))
MAX_ART = int(os.environ.get("INTEL_MAX_ART", "40"))
NUM = os.environ.get("INTEL_SEARCH_NUM", "3")
MAX_FEED = int(os.environ.get("INTEL_MAX_FEED", "800"))
MIN_BODY = int(os.environ.get("INTEL_MIN_BODY", "400"))
Q_MIN = int(os.environ.get("INTEL_QUALITY_MIN", "55"))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# 第 4 路：收藏夹公开机构 RSS（智库/政府/国际媒体/NGO/OSINT），美国节点直连不烧 Jina
INST_SRC = os.path.join(ROOT, "targets", "institute_sources.json")
INST_DAYS = int(os.environ.get("INTEL_INST_DAYS", "7"))        # 机构周报/月报，窗口 7 天
INST_PER_FEED = int(os.environ.get("INTEL_INST_PER_FEED", "15"))  # 每源每轮最多评估条数
INST_MAX = int(os.environ.get("INTEL_INST_MAX", "120"))        # RSS 自带正文（免费）每轮入库上限
INST_DEEP = int(os.environ.get("INTEL_INST_DEEP", "10"))       # 摘要过短需 Jina 深抓的机构稿上限
INST_WORKERS = int(os.environ.get("INTEL_INST_WORKERS", "8"))


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
    if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", u):
        if u.startswith("reuters.com/"):
            u = "www." + u
        return "https://" + u
    if u.startswith("/"):
        p = urllib.parse.urlparse(base)
        return f"{p.scheme}://{p.netloc}{u}"
    return urllib.parse.urljoin(base, u)


def host_of(u):
    try:
        return urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def in_any(u, domains):
    h = host_of(u)
    return any(d in h for d in domains)


# ---------- 日期 ----------
def pick_date(*texts):
    for t in texts:
        if not t:
            continue
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", t)
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", t)
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", t)
        if m:
            return _date(m.group(1), m.group(2), m.group(3))
    return None


def _date(y, mo, d):
    try:
        return datetime.date(int(y), int(mo), int(d))
    except Exception:
        return None


def fresh(dt, days=DAYS):
    if dt is None:
        return False
    delta = (datetime.datetime.utcnow().date() - dt).days
    return -1 <= delta <= days


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


# ---------- 质量层（确定性打分，不调用大模型、零额外 token） ----------
_ORG_ZH = re.compile(r"(部|委|局|署|院|府|军|党|盟|会|组织|协会|基金会|大学|研究所|使馆|外交部|国防部|国会|议会|"
                     r"联盟|阵线|运动|政府|警方|官员|部长|总统|主席|领导人|法院|检察|国安|情报)")
_ORG_EN = re.compile(r"(?i)(ministry|department|congress|parliament|senate|council|committee|government|"
                     r"officials?|minister|president|secretary|pentagon|state dept|ngo|coalition|alliance|"
                     r"activists?|protesters?|dissident|police|court|agency|nato|embassy|regulator|lawmaker)")
_MARKET = re.compile(r"(?i)(buy now|click to buy|subscribe now|sign up now|shop now|free trial|立即下单|"
                     r"马上购买|关注领取|加微信|扫码进群|联系客服|包邮|优惠券)")


def _trigrams(s):
    s = re.sub(r"\s+", "", s)[:320]
    return set(s[i:i + 3] for i in range(len(s) - 2))


def is_duplicate(text, existing):
    t = _trigrams(text)
    if len(t) < 24:
        return False
    for g in existing:
        union = len(t | g)
        if union and len(t & g) / union >= 0.55:
            return True
    return False


def quality_score(text, junk_re, paywall_re, ad_re):
    """返回 (0-100 分, 是否硬付费墙, 原因列表)。事实要素越密、结构越完整越高；广告/付费墙/标题党扣分。"""
    n = len(text)
    score, why = 0, []
    # 1) 长度 0-30
    score += 30 if n >= 1800 else 22 if n >= 1000 else 14 if n >= 600 else 6
    # 2) 事实要素 0-35：数字 / 引语 / 机构专有词
    score += min(len(re.findall(r"\d", text)) // 3, 12)
    score += min(len(re.findall(r"[“\"「『]", text)) * 4, 10)
    score += min((len(_ORG_ZH.findall(text)) + len(_ORG_EN.findall(text))) * 2, 13)
    # 3) 结构 0-15
    paras = [p for p in text.split("\n") if len(p.strip()) > 20]
    sents = len(re.findall(r"[。！？.!?]", text))
    if len(paras) >= 5:
        score += 8
    if sents >= 12:
        score += 7
    # 4) 广告 / 付费墙 / 营销（扣分 / 硬标记）
    if paywall_re.search(text):
        score -= 30; why.append("paywall")
    score -= min(len(ad_re.findall(text)) * 8, 24)
    score -= min(len(junk_re.findall(text)) * 2, 8)
    # 5) 标题党 / 情绪密度
    if n > 0:
        emo = text.count("!") + text.count("！") + text.count("?") + text.count("？")
        if emo / max(n / 100, 1) > 6:
            score -= 8; why.append("clickbait")
    if _MARKET.search(text):
        score -= 15; why.append("marketing")
    return max(0, min(100, score)), ("paywall" in why), why


def load_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return []
    return []


def feed_get(url, timeout=20):
    """直连公开 RSS/Atom（不走 Jina，零 token）。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, */*"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def _lc(tag):
    return (tag or "").split("}")[-1].lower()


def _child(el, name):
    for c in el:
        if _lc(c.tag) == name:
            return c
    return None


def _all_text(el):
    if el is None:
        return ""
    parts = []
    for c in el.iter():  # 首个即 el 自身，取 text/tail 即可，勿重复计入 el.text
        parts.append(c.text or ""); parts.append(c.tail or "")
    s = "".join(parts)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def rss_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).date()
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


def parse_rss_items(body, feed_url):
    """解析 RSS2.0 / Atom / RDF 条目，正文取 content:encoded/content/summary/description 中最长者。"""
    root = ET.fromstring(body)
    out = []
    for e in (x for x in root.iter() if _lc(x.tag) in ("item", "entry")):
        title = _all_text(_child(e, "title"))
        link = ""
        for c in e:
            if _lc(c.tag) != "link":
                continue
            href = c.get("href")
            if href and (not c.get("rel") or c.get("rel") == "alternate"):
                link = href; break
            if not href and (c.text or "").strip():
                link = c.text.strip(); break
        if link:
            link = urllib.parse.urljoin(feed_url, link)
        dnode = None
        for nm in ("pubdate", "published", "updated", "date", "issued", "created"):
            c = _child(e, nm)
            if c is not None and (c.text or "").strip():
                dnode = c; break
        d = rss_date(dnode.text if dnode is not None else "")
        text = ""
        for nm in ("encoded", "content", "summary", "description", "subtitle"):
            tx = _all_text(_child(e, nm))
            if len(tx) > len(text):
                text = tx
        out.append({"title": title[:200], "link": link, "date": d, "text": text})
    return out


def lang_of(text):
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    lat = len(re.findall(r"[A-Za-z]", text or ""))
    return "zh" if cjk >= max(8, lat * 0.08) else "en"


def main():
    if not KEY:
        print("[intel] 未配置 JINA_KEY，跳过"); return
    os.makedirs(DATA, exist_ok=True)
    cfg = json.load(open(SRC, encoding="utf-8"))
    sections, topics = cfg["sections"], cfg["search_categories"]
    watches = cfg.get("watch_categories", [])
    block_global = tuple(cfg.get("block_global", []))
    social = cfg.get("social_domains", [])
    shell = cfg.get("shell_social", [])
    news_block = tuple(list(block_global) + social)  # 新闻路不混社媒
    rel = re.compile(cfg.get("relevance_re", "."))
    junk_re = re.compile("|".join(re.escape(x) for x in cfg.get("junk_markers", [])))
    paywall_re = re.compile("|".join(cfg.get("paywall_markers", [])))
    ad_re = re.compile("|".join(cfg.get("ad_markers", [])))
    after_news = (datetime.datetime.utcnow().date() - datetime.timedelta(days=DAYS)).isoformat()
    after_watch = (datetime.datetime.utcnow().date() - datetime.timedelta(days=WATCH_DAYS)).isoformat()
    hour = datetime.datetime.utcnow().hour
    force = bool(os.environ.get("INTEL_FORCE_SEARCH"))
    do_search = hour in (0, 12) or force   # 议题新闻每天 2 轮
    do_watch = hour == 0 or force          # 反华人物/活动/路径/组织体量大，每天 1 轮控成本

    feed = load_json(FEED)
    # 旧版条目迁移：按当前质量标准补字段并重新打分，够格的一并进入 brief
    for x in feed:
        if "body_from" not in x:
            sc, hard, _ = quality_score(x.get("content", ""), junk_re, paywall_re, ad_re)
            x.update({"body_from": "full", "route": x.get("route", "news"),
                      "needs_deepdive": False, "quality_score": sc,
                      "usable": (not hard and sc >= Q_MIN)})
    seen = {x["url"] for x in feed}
    existing_sets = [_trigrams(x.get("content", "")) for x in feed]
    candidates = {}
    counts = {"section": 0, "topic": 0, "watch_full": 0, "watch_snippet": 0}

    def add(url, source, lang, cat, via, route, block, body_from="full",
            snippet=None, hint_date=None, hint_title=""):
        if not url or url in seen or url in candidates:
            return
        if any(b in url.lower() for b in block):
            return
        candidates[url] = {"url": url, "source": source, "lang": lang, "cat": cat, "via": via,
                           "route": route, "body_from": body_from, "snippet": snippet,
                           "hint_date": hint_date, "hint_title": hint_title}
        counts["watch_snippet" if body_from == "snippet"
               else "watch_full" if route == "watch" else via] = \
            counts.get("watch_snippet" if body_from == "snippet"
                       else "watch_full" if route == "watch" else via, 0) + 1

    # 1) 栏目/首页轮询（每 6 小时）
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
            if d is None or fresh(d, DAYS):
                add(u, sec["name"], sec.get("lang", "?"), sec["cat"], "section", "news", news_block, hint_date=d)
                kept += 1
        print(f"[section] {sec['name']}: 链接{len(links)} 候选{kept} tokens={tok}", flush=True)
        time.sleep(0.5)

    # 2)+3) 议题检索 + watch 追踪（每天 UTC0/12；手动 dispatch 强制）
    if do_search:
        for tp in topics:
            items, tok = search(tp["q"], after_news)
            n = 0
            for it in items:
                u = it.get("url", "")
                blob = " ".join([it.get("title", ""), it.get("description", ""), it.get("content", "")])
                d = pick_date(it.get("date", ""), it.get("publishedTime", ""), u)
                if not rel.search(blob) or (d and not fresh(d, DAYS)):
                    continue
                add(u, tp["cat"], "en", tp["cat"], "topic", "news", news_block,
                    hint_date=d, hint_title=it.get("title", "")); n += 1
            print(f"[topic] {tp['cat']}: 采纳{n} tokens={tok}", flush=True)
            time.sleep(0.4)
    else:
        print(f"[topic] UTC {hour} 点本轮不跑议题检索（每天 UTC 0/12）", flush=True)

    if do_watch:
        for wc in watches:
            wn = 0
            for q in wc["queries"]:
                items, tok = search(q, after_watch, num=NUM)
                for it in items:
                    u = it.get("url", "")
                    blob = " ".join([it.get("title", ""), it.get("description", ""), it.get("content", "")])
                    d = pick_date(it.get("date", ""), it.get("publishedTime", ""), u)
                    if not rel.search(blob) or (d and not fresh(d, WATCH_DAYS)):
                        continue
                    title = (it.get("title", "") or "").strip()
                    if in_any(u, shell):  # 抓不到正文的社媒壳：只存线索快照
                        snip = (title + "\n\n" + (it.get("description", "") or it.get("content", "")[:600])).strip()
                        if len(snip) < 60:
                            continue
                        add(u, wc["cat"], "?", wc["cat"], "watch", "watch", block_global,
                            body_from="snippet", snippet=snip, hint_date=d, hint_title=title)
                    else:                  # Reddit / change.org / 新闻报告站：深抓全文
                        add(u, wc["cat"], "?", wc["cat"], "watch", "watch", block_global,
                            hint_date=d, hint_title=title)
                    wn += 1
                time.sleep(0.3)
            print(f"[watch] {wc['cat']}: 采纳{wn}", flush=True)
    else:
        print(f"[watch] UTC {hour} 点本轮不跑反华追踪（每天 UTC 0 一次）", flush=True)

    # 3.5) 收藏夹公开机构 RSS（智库/政府/国际媒体/NGO/OSINT）：美国节点直连、零 Jina，每轮都跑
    inst_n = 0
    if os.path.exists(INST_SRC):
        inst_srcs = [s for s in load_json(INST_SRC)
                     if s.get("status") == "active" and s.get("feed_url")
                     and "sitemap" not in s["feed_url"]]
        inst_srcs.sort(key=lambda s: -int(s.get("china_hits") or 0))
        uniq, seen_feed = [], set()
        for s in inst_srcs:
            if s["feed_url"] in seen_feed:
                continue
            seen_feed.add(s["feed_url"]); uniq.append(s)
        inst_cut = datetime.datetime.utcnow().date() - datetime.timedelta(days=INST_DAYS)

        def fetch_src(s):
            st, body = feed_get(s["feed_url"])
            items = []
            if st == 200 and body and not body.startswith("EXC"):
                try:
                    items = parse_rss_items(body, s["feed_url"])
                except Exception:
                    items = []
            return s, items

        with ThreadPoolExecutor(max_workers=INST_WORKERS) as ex:
            for s, items in (fu.result() for fu in as_completed([ex.submit(fetch_src, x) for x in uniq])):
                k = 0
                for it in items[:INST_PER_FEED]:
                    u = it["link"]
                    if not u or u in seen or u in candidates:
                        continue
                    if it["date"] and it["date"] < inst_cut:
                        continue
                    blob = it["title"] + " " + it["text"][:1000]
                    if not rel.search(blob) or any(b in u.lower() for b in block_global):
                        continue
                    cand = {"url": u, "source": s.get("name") or s["host"],
                            "lang": lang_of(blob), "cat": s.get("cat", "institute"),
                            "via": "institute", "route": "institute",
                            "hint_date": it["date"], "hint_title": it["title"]}
                    if s.get("mode") == "titles_only":
                        snip = (it["title"] + "\n\n" + it["text"][:600]).strip()
                        if len(snip) < 60:
                            continue
                        cand.update({"body_from": "snippet", "snippet": snip})
                    elif len(it["text"]) >= MIN_BODY:
                        cand.update({"body_from": "feed", "snippet": None, "content": it["text"]})
                    else:
                        cand.update({"body_from": "full", "snippet": None})
                    candidates[u] = cand; k += 1; inst_n += 1
                if k:
                    print(f"[inst] {str(s.get('name', ''))[:22]}: +{k}", flush=True)
        print(f"[inst] 机构 RSS 本轮候选 {inst_n}（活跃源 {len(uniq)}）", flush=True)

    # 4) 正文 / 快照 + 质量过滤（按日期新->旧，限量控成本）
    cand = list(candidates.values())
    cand.sort(key=lambda x: x["hint_date"] or datetime.date(2000, 1, 1), reverse=True)
    snip_cand = [c for c in cand if c["body_from"] == "snippet"]             # 线索快照：零 token，全保留
    feed_cand = [c for c in cand if c["body_from"] == "feed"][:INST_MAX]     # 机构 RSS 自带全文：零 token
    deep_other = [c for c in cand if c["body_from"] == "full" and c["route"] != "institute"][:MAX_ART]
    deep_inst = [c for c in cand if c["body_from"] == "full" and c["route"] == "institute"][:INST_DEEP]
    deep_cand = deep_other + deep_inst                                       # 需 Jina 深抓：限量控成本
    today = datetime.datetime.utcnow().date()
    f = {"fetch_fail": 0, "not_fresh": 0, "too_short": 0, "not_rel": 0, "duplicate": 0,
         "paywall": 0, "low_quality": 0, "usable": 0, "snippet_lead": 0}
    full_total = 0
    added = 0
    for c in snip_cand + feed_cand + deep_cand:
        is_snip = c["body_from"] == "snippet"
        is_feed = c["body_from"] == "feed"
        if c["route"] == "institute":
            window = INST_DAYS
        elif c["route"] == "watch":
            window = WATCH_DAYS
        else:
            window = DAYS
        md = ""
        if is_snip:
            title, pub, text, tok = c["hint_title"], "", c["snippet"], "0(snippet)"
        elif is_feed:
            title, pub, text, tok = c["hint_title"], "", c.get("content", ""), "0(feed)"
        else:
            full_total += 1
            st, md, tok = reader(c["url"])
            if st != 200 or not md or md.startswith("EXC"):
                f["fetch_fail"] += 1; print(f"  x 抓取失败 HTTP{st} {c['url'][:64]}", flush=True); continue
            title, pub, text = clean_article(md)
        if is_feed:
            d = c["hint_date"]
        else:
            d = c["hint_date"] or (None if is_snip else pick_date(pub, c["url"], md[:4000]))
        inferred = False
        if not fresh(d, window):
            if d is None and len(text) >= (120 if is_snip else MIN_BODY):
                d, inferred = today, True  # 栏目/搜索已限窗口，无精确日期按当天计并标记
            else:
                f["not_fresh"] += 1; continue
        min_len = 120 if is_snip else MIN_BODY
        if len(text) < min_len:
            f["too_short"] += 1; print(f"  x 过短({len(text)}) {c['url'][:64]}", flush=True); continue
        if not rel.search(title + " " + text[:800]):
            f["not_rel"] += 1; print(f"  x 不相关 {(title or c['url'])[:48]}", flush=True); continue
        if is_snip:
            score, hard, why = 45, False, ["social_snippet"]
        else:
            if is_duplicate(text, existing_sets):
                f["duplicate"] += 1; print(f"  x 重复通稿 {(title or c['url'])[:48]}", flush=True); continue
            score, hard, why = quality_score(text, junk_re, paywall_re, ad_re)
            if hard:
                f["paywall"] += 1; print(f"  x 付费墙 {c['url'][:64]}", flush=True); continue
        usable = (not is_snip) and score >= Q_MIN
        if not usable and not is_snip:
            f["low_quality"] += 1; print(f"  x 低质({score}分,{','.join(why)}) {(title or c['url'])[:42]}", flush=True); continue
        if is_snip:
            f["snippet_lead"] += 1
        if usable:
            f["usable"] += 1
        item = {
            "id": hashlib.sha1(c["url"].encode()).hexdigest()[:16],
            "title": (title or c["hint_title"] or "(无标题)").strip()[:200],
            "url": c["url"], "source": c["source"], "lang": c["lang"], "cat": c["cat"],
            "route": c["route"], "body_from": c["body_from"],
            "quality_score": score, "usable": usable,
            "needs_deepdive": is_snip,
            "published": d.isoformat(), "date_inferred": inferred,
            "fetched_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "summary": re.sub(r"\s+", " ", text)[:240],
            "content": text,
        }
        feed.insert(0, item); seen.add(c["url"]); added += 1
        existing_sets.append(_trigrams(text))
        tag = "线索" if is_snip else ("可用" if usable else "存档")
        print(f"  +[{tag}|{score}分|{c['cat']}] {item['title'][:42]} ({item['published']}"
              f"{'?' if inferred else ''}) {len(text)}字 tok={tok}", flush=True)
        if not is_snip and not is_feed:
            time.sleep(0.4)  # 仅 Jina 深抓限速；RSS 自带正文与线索不耗 token

    feed.sort(key=lambda x: x.get("published", ""), reverse=True)
    feed = feed[:MAX_FEED]
    json.dump(feed, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    brief = sorted([x for x in feed if x.get("usable")],
                   key=lambda x: (x.get("quality_score", 0), x.get("published", "")), reverse=True)
    json.dump(brief, open(BRIEF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    dropped = sum(f[k] for k in ("fetch_fail", "not_fresh", "too_short", "not_rel", "duplicate", "paywall", "low_quality"))
    print(f"\n[intel] 候选构成: {counts}", flush=True)
    print(f"[intel] 全文深抓 {full_total} 篇，丢弃 {dropped}（{f}），社媒线索 {f['snippet_lead']}，"
          f"可直接研判 usable {f['usable']} 篇", flush=True)
    if full_total:
        print(f"[intel] 全文口径滤除率 {dropped}/{full_total} = {round(100*dropped/full_total)}%；"
              f"供模型研判仅取 intel_brief.json（{len(brief)} 篇）", flush=True)
    print(f"[intel] 本轮新增 {added}，feed 累计 {len(feed)}，brief 累计 {len(brief)}", flush=True)
    print("INTEL_DONE")


if __name__ == "__main__":
    main()
