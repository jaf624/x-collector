# -*- coding: utf-8 -*-
"""Feed 自动发现：把"死源"救成"活源"（纯代码、零 token、零第三方依赖）。

原理（跨领域借来的三条规律）：
  1. 绝大多数站点仍偷偷保留着 RSS——只是入口没写在导航上，藏在 <link rel="alternate">；
  2. 老站常见固定路径（/feed、/rss、/rss.xml、/feed.xml、/atom.xml、/index.xml、/?feed=rss2）；
  3. 有 sitemap 的站，sitemap 里往往能找到 news/blog 的时间线入口。

做法：对 targets 里 last_probe_status 为 dead/empty 的 host，逐条探测上述入口，
只认"能解析出条目"的结果，把新 feed 写回 targets（status=active、grade=C、added=auto-discover）。
所有请求走 netguard（限速 + 熔断 + TLS 指纹伪装），不并发打同一 host。
"""
import json, os, re, sys, datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netguard

TARGETS = "targets/institute_sources.json"
OUT = "data/feed_discovery.json"

PATHS = ["/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml",
         "/feeds/posts/default", "/?feed=rss2", "/rss/index.xml", "/en/feed"]
CONTENT_TYPES = ("application/rss", "application/atom", "text/xml", "application/xml")


def has_items(text):
    if not text or len(text) < 200:
        return 0
    head = text[:3000].lower()
    if not ("<rss" in head or "<feed" in head or "<rdf" in head):
        return 0
    return len(re.findall(r"<item[\s>]", text)) + len(re.findall(r"<entry[\s>]", text))


def link_tag_feeds(base, html):
    """从页面 <link rel=alternate> 里抓 feed 地址（比猜路径可靠得多）。"""
    out = []
    for m in re.finditer(r'<link[^>]+rel=["\']?(?:alternate|feed)[^>]*>', html, re.I):
        tag = m.group(0)
        if "rss" not in tag.lower() and "atom" not in tag.lower() and "xml" not in tag.lower():
            continue
        hm = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if not hm:
            continue
        u = hm.group(1)
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = base.rstrip("/") + u
        elif not u.startswith("http"):
            u = base.rstrip("/") + "/" + u
        out.append(u)
    return out[:3]


def discover(entry):
    host = entry.get("host") or ""
    base = (entry.get("base") or ("https://" + host)).rstrip("/")
    found = []

    # 1) 首页 link 标签
    st, html, meta = netguard.fetch(base, timeout=12)
    if st == 200 and html:
        for u in link_tag_feeds(base, html[:200000]):
            fs, body, _ = netguard.fetch(u, timeout=12)
            n = has_items(body)
            if n >= 3:
                found.append((u, n))
                break

    # 2) 固定路径
    if not found:
        for p in PATHS:
            fs, body, _ = netguard.fetch(base + p, timeout=10)
            n = has_items(body)
            if n >= 3:
                found.append((base + p, n))
                break
    return host, found


def main():
    src = json.load(open(TARGETS, encoding="utf-8"))
    dead = [s for s in src
            if s.get("last_probe_status") in ("dead", "empty") and not s.get("feed_url")]
    dead += [s for s in src
             if s.get("last_probe_status") in ("dead", "empty") and s.get("feed_url")]
    seen, todo = set(), []
    for s in dead:
        h = s.get("host")
        if h and h not in seen:
            seen.add(h)
            todo.append(s)
    todo.sort(key=lambda s: -(s.get("china_hits") or 0))   # 涉华多的先救
    todo = todo[: int(os.environ.get("FD_MAX", "260"))]
    print("待救 host %d" % len(todo), flush=True)

    res = {}
    with ThreadPoolExecutor(max_workers=6) as ex:   # 6 线程 + 每 host 限速，整体不暴力
        for host, found in ex.map(discover, todo):
            res[host] = found

    today = datetime.date.today().isoformat()
    revived, added = 0, 0
    out_rows = []
    for s in src:
        h = s.get("host")
        if h in res and res[h]:
            url, n = res[h][0]
            if s.get("feed_url"):
                s["feed_url"] = url
                s["last_probe_status"] = "alive"
            else:
                s["feed_url"] = url
                s["status"] = "active"
                s["grade"] = s.get("grade") or "C"
                added += 1
            s["last_probe"] = today
            s["last_probe_items"] = n
            s["last_probe_age"] = 0
            s["last_probe_status"] = "alive"
            revived += 1
            out_rows.append({"host": h, "feed": url, "items": n})
    json.dump(src, open(TARGETS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    summary = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
               "probed_hosts": len(todo), "revived": revived, "new_feeds": added,
               "guard": netguard.summary()}
    os.makedirs("data", exist_ok=True)
    json.dump(summary, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
