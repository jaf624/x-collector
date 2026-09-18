#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 公开频道"自动发现器"（GitHub Actions 美国节点，免登录）。

合规设计：
  - 只通过公开搜索引擎(s.jina.ai / DDG / Bing)检索 t.me 公开频道，不登录、不加入、不碰私群；
  - 只产出"待审候选池" data/tg_discovered.json，status=pending_review，绝不自动纳入正式监测；
  - 候选仅含频道级元数据(用户名/标题/描述/链接/活跃度/涉华与各类别命中计数/相关度分)，
    不保存任何消息正文、不下载媒体；高敏类别只记命中数；
  - 最终是否监测由使用者(单位)人工审核确认后写入 business_channels，人在回路、全程留痕。
"""
import os, re, json, ssl, html, time, datetime, urllib.request, urllib.error, urllib.parse
import telegram_collect as tc

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "tg_discovered.json")
CFG = os.path.join(ROOT, "targets", "telegram.json")
KEY = os.environ.get("JINA_KEY", "").strip()
CTX = tc.CTX
BLOCK = {"telegram", "s", "share", "joinchat", "addstickers", "addtheme", "addemoji", "login",
         "proxy", "socks", "settings", "premium", "username", "durov", "auth", "stickers",
         "giftcode", "invoice", "wallet", "buy", "stars", "android", "ios", "desktop", "web",
         "blog", "press", "tos", "privacy", "apps", "dl", "download"}


def get(url, headers=None, timeout=70):
    return tc.get(url, headers, timeout)


def extract_channels(body):
    out = set()
    texts = [body]
    for m in re.finditer(r"uddg=([^&\"'<>]+)", body):
        texts.append(urllib.parse.unquote(m.group(1)))
    b = body
    for _ in range(3):
        d = urllib.parse.unquote(b)
        if d == b:
            break
        b = d
    texts.append(b)
    for t in texts:
        for m in re.finditer(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})", t):
            n = m.group(1)
            if n.lower() not in BLOCK and not n.isdigit():
                out.add(n)
    return out


def search(q):
    enc = urllib.parse.quote(q)
    for label, u, hdr in [
        ("s.jina", f"https://s.jina.ai/{enc}", {"Authorization": f"Bearer {KEY}", "Accept": "text/plain"}),
        ("DDG", f"https://html.duckduckgo.com/html/?q={enc}", None),
        ("Jina-Bing", f"https://r.jina.ai/https://www.bing.com/search?q={enc}&setlang=en", {"Authorization": f"Bearer {KEY}"}),
    ]:
        st, body = get(u, hdr)
        names = extract_channels(body)
        print(f"  [{label}] HTTP{st} len={len(body)} 候选={len(names)}", flush=True)
        if names:
            return names
    return set()


def verify(name, cfg, china_re, cats):
    st, body = get(f"https://t.me/s/{name}", timeout=30)
    if st != 200:
        return None
    title = ""
    mt = re.search(r'property="og:title" content="([^"]+)"', body)
    if mt:
        title = html.unescape(mt.group(1))
    desc = ""
    md = re.search(r'property="og:description" content="([^"]*)"', body)
    if md:
        desc = html.unescape(md.group(1))[:160]
    posts = tc.parse_widgets(body, name)
    if not posts:
        return None
    dates = [p["pub"] for p in posts if p["pub"]]
    latest = max(dates) if dates else ""
    today = datetime.datetime.utcnow().date()
    recent3 = recent7 = 0
    for d in dates:
        try:
            age = (today - datetime.date.fromisoformat(d)).days
            recent3 += age <= 3; recent7 += age <= 7
        except Exception:
            pass
    china_hits, related, cat_hits, media = 0, 0, {}, 0
    for p in posts:
        t = p.get("text", "")
        if not t:
            continue
        cn = len(china_re.findall(t)); china_hits += cn
        hit_any = False
        for c in cats:
            if c["re"].search(t):
                cat_hits[c["name"]] = cat_hits.get(c["name"], 0) + 1; hit_any = True
        if cn and hit_any:
            related += 1
        media += len(p.get("media", []))
    score = related * 10 + (8 if recent3 else (4 if recent7 else 0)) + min(len(posts), 20) * 0.5 + min(china_hits, 10) * 0.3
    return {"name": name, "url": f"https://t.me/{name}", "preview": f"https://t.me/s/{name}",
            "title": title[:60], "desc": desc, "posts_in_page": len(posts), "latest": latest,
            "recent3": recent3, "recent7": recent7, "china_hits": china_hits,
            "cat_hits": dict(sorted(cat_hits.items(), key=lambda x: -x[1])[:5]),
            "related_msgs": related, "media_count_only": media, "score": round(score, 1)}


def main():
    cfg = json.load(open(CFG, encoding="utf-8"))
    dcfg = cfg.get("discover", {})
    china_re = tc.build_re(cfg["china_keywords"])
    cats = [{"key": c["key"], "name": c["name"], "re": tc.build_re(c["keywords"])} for c in cfg["categories"]]
    existing_biz = {c if isinstance(c, str) else c["name"] for c in cfg.get("business_channels", [])}
    os.makedirs(DATA, exist_ok=True)
    pool = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else []
    known = {x["name"] for x in pool} | existing_biz

    found = {}
    for q in cfg["discover_queries"]:
        print(f"QUERY: {q}", flush=True)
        for n in search(q):
            found[n] = True
        time.sleep(1.2)
    todo = [n for n in sorted(found) if n not in known][:dcfg.get("verify_max", 24)]
    print(f"\n搜索去重候选 {len(found)}，新增待验证 {len(todo)}", flush=True)

    added = 0
    for name in todo:
        v = verify(name, cfg, china_re, cats)
        if not v:
            print(f"  - {name}: 非公开/无消息", flush=True); continue
        ok = (v["posts_in_page"] >= dcfg.get("min_posts", 5)
              and v["related_msgs"] >= dcfg.get("min_related", 2)
              and v["score"] >= dcfg.get("score_min", 22))
        mark = "★入池" if ok else "  排除"
        print(f"  {mark} {name} | {v['title'][:24]} | 消息{v['posts_in_page']} 涉华风险{v['related_msgs']} "
              f"分{v['score']} 最近{v['latest']} 类{list(v['cat_hits'])[:2]}", flush=True)
        if ok:
            v["status"] = "pending_review"
            v["discovered_at"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
            pool.append(v); known.add(name); added += 1
        time.sleep(0.4)

    pool.sort(key=lambda x: -x["score"])
    pool = pool[:dcfg.get("keep_max", 120)]
    json.dump(pool, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    pend = sum(1 for x in pool if x["status"] == "pending_review")
    print(f"\n[tg-discover] 本轮新增入池 {added}；候选池累计 {len(pool)}（待审 {pend}）；TG_DISCOVER_DONE", flush=True)


if __name__ == "__main__":
    main()
