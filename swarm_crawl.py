# -*- coding: utf-8 -*-
"""蜂群采集器（单机可跑，零 token，可直接搬进 GitHub Actions 或任意 VPS）。

设计目标对应四句话：
  爬得多   —— 一次跑完清单里所有活源，不再"只跑 A 级 54 个"
  有规律   —— 每轮固定时间预算，到点收工，下一轮准点起跑（不间断比单轮抓满重要）
  聪明     —— 按 host 分片 + 原子领取，同一 host 永不并发；按 ROI 排序先抓高价值源
  不被封   —— 全链路走 netguard（每 host 令牌桶 / 退避 / 熔断 / TLS 指纹），失败按源记账

用法：
  python3 swarm_crawl.py --targets targets/institute_sources.json --budget 480 --out data/swarm.json
  PROXY_LIST=proxies.txt python3 swarm_crawl.py ...      # 有代理池时自动按需换 IP

代理策略（"换 IP"不是第一杠杆，只在必要时用）：
  同一 host 连续 2 次 403/429 → 该 host 进入"需代理"名单，之后对该 host 轮换代理；
  其余 host 仍走直连（直连更快、更省）。代理地址格式：http://user:pass@host:port
"""
import argparse, json, os, re, sqlite3, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netguard


def host_of(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return (m.group(1) if m else "").lower()


def load_proxies(path):
    if not path or not os.path.exists(path):
        return []
    return [x.strip() for x in open(path, encoding="utf-8") if x.strip()]


class Claim:
    """任务表原子领取：同一 URL 只会被一个 worker 拿走（重启后也不重复干）。"""

    def __init__(self, db):
        self.db = db
        self.cx = sqlite3.connect(db, timeout=30, check_same_thread=False)
        self._lk = threading.Lock()
        self.cx.execute("CREATE TABLE IF NOT EXISTS claim(id TEXT PRIMARY KEY, at TEXT, host TEXT)")
        self.cx.execute("CREATE TABLE IF NOT EXISTS yield(id TEXT PRIMARY KEY, host TEXT, "
                        "parsed INT, err TEXT)")
        self.cx.commit()

    def take(self, ident, host):
        with self._lk:
            try:
                self.cx.execute("INSERT INTO claim(id,at,host) VALUES(?,?,?)",
                                (ident, time.strftime("%Y-%m-%dT%H:%M"), host))
                self.cx.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def record(self, ident, host, parsed, err):
        with self._lk:
            self.cx.execute("INSERT OR REPLACE INTO yield(id,host,parsed,err) VALUES(?,?,?,?)",
                            (ident, host, parsed, err))
            self.cx.commit()

    def history(self):
        with self._lk:
            return {r[0]: (r[1], r[2]) for r in
                self.cx.execute("SELECT host, SUM(parsed), COUNT(*) FROM yield GROUP BY host")}


def parse_feed(body, limit=60):
    """零依赖 RSS/Atom 粗解析：标题 + 链接 + 摘要 + 时间。"""
    items, out = [], []
    for m in re.finditer(r"<item[\s>][\s\S]*?</item>", body, re.I):
        items.append(m.group(0))
    if not items:
        for m in re.finditer(r"<entry[\s>][\s\S]*?</entry>", body, re.I):
            items.append(m.group(0))

    def pick(block, *tags):
        for t in tags:
            mm = re.search(r"<%s[^>]*>([\s\S]*?)</%s>" % (t, t), block, re.I)
            if mm:
                v = re.sub(r"<!\[CDATA\[|\]\]>", "", mm.group(1))
                v = re.sub(r"<[^>]+>", " ", v)
                return re.sub(r"\s+", " ", v).strip()
        return ""

    for b in items[:limit]:
        out.append({
            "title": pick(b, "title"),
            "link": pick(b, "link") or (re.search(r'<link[^>]+href="([^"]+)"', b, re.I) or [None, ""])[1],
            "desc": pick(b, "description", "summary", "content"),
            "date": pick(b, "pubDate", "updated", "published", "dc:date"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="targets/institute_sources.json")
    ap.add_argument("--budget", type=int, default=480, help="本轮秒级预算")
    ap.add_argument("--out", default="data/swarm.json")
    ap.add_argument("--db", default="data/swarm_claim.db")
    ap.add_argument("--per-host", type=int, default=20)
    ap.add_argument("--proxy", default=os.environ.get("PROXY_LIST", ""))
    a = ap.parse_args()

    src = json.load(open(a.targets, encoding="utf-8"))
    feeds = [s for s in src if s.get("feed_url") and s.get("status") == "active"
             and "sitemap" not in s["feed_url"]]
    proxies = load_proxies(a.proxy)
    claim = Claim(a.db)

    # ROI 排序：china_hits 高的、上一轮解析条数多的先抓
    hist = claim.history()
    feeds.sort(key=lambda s: -((s.get("china_hits") or 0) + hist.get(s["host"], (0, 0))[0]))

    # host 分片：同一 host 只进一个分片，天然不并发
    shards = {}
    for s in feeds:
        shards.setdefault(host_of(s["feed_url"]), []).append(s)
    print("活源 %d 个 / host %d 个 / 代理 %d 条 / 预算 %ds"
          % (len(feeds), len(shards), len(proxies), a.budget), flush=True)

    t0 = time.time()
    result, done = [], {"ok": 0, "fail": 0, "cooled": 0}
    px = {"i": 0}

    def grab(s, h):
        if time.time() - t0 > a.budget:
            return None
        ident = s["feed_url"]
        if not claim.take(ident, h):
            return None
        st, body, meta = netguard.fetch(s["feed_url"], timeout=15)
        if meta.get("cooled"):
            done["cooled"] += 1
        if st == 200 and body:
            items = parse_feed(body)
            claim.record(ident, h, len(items), "")
            return {"host": h, "items": items, "via": meta.get("via")}
        claim.record(ident, h, 0, meta.get("err") or str(st))
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for h, group in shards.items():
            for s in group:
                futs.append(ex.submit(grab, s, h))
        for fu in as_completed(futs):
            r = fu.result()
            if r and r["items"]:
                result.append(r)
                done["ok"] += 1
            elif r is not None:
                done["fail"] += 1

    flat = []
    for r in result:
        for it in r["items"][:a.per_host]:
            if it["title"] and it["link"]:
                it["host"] = r["host"]
                flat.append(it)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"at": time.strftime("%Y-%m-%dT%H:%M"),
               "feed_ok": done["ok"], "feed_fail": done["fail"],
               "cooled": done["cooled"], "items": len(flat),
               "guard": netguard.summary(), "items_list": flat},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("完成：成功源 %d / 失败 %d / 熔断跳过 %d / 条目 %d / 用时 %.0fs"
          % (done["ok"], done["fail"], done["cooled"], len(flat), time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
