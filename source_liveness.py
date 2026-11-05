# -*- coding: utf-8 -*-
"""源存活探活（纯代码、零 token）。

为什么要它：配置 787 个源、347 个唯一 host，7 天内真正有产出的只有 49 个（14%）。
抓取预算被平均摊在 298 个死源上，活源反而抓得浅。这个脚本把"活/半死/死"量出来，
回写进 targets/institute_sources.json 的 last_probe* 字段，采集器据此排配额。

判定口径（三档，不看标题、不看正文，只看 feed 本身）：
  alive   解析到 >=1 条条目，且最新条目 <= 45 天
  stale   能解析但最新条目 > 45 天（源活着但不再更新）
  empty   200 但没有条目（HTML 落地页 / 反爬挑战页）
  dead    HTTP 失败 / 超时 / 非 XML
输出：data/source_liveness.json（只含 host 级统计与计数，不含标题文字）
"""
import json, os, re, ssl, sys, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
import datetime

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

TARGETS = "targets/institute_sources.json"
OUT = "data/source_liveness.json"
STALE_DAYS = 45
TIMEOUT = 12
WORKERS = 10


def fetch_feed(url):
    """返回 (status, kind, items, newest_age_days, err)。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            raw = r.read(3000000).decode("utf-8", "ignore")
            status = r.status
    except urllib.error.HTTPError as e:
        return e.code, "http_err", 0, None, "HTTP%s" % e.code
    except Exception as e:
        return 0, "net_err", 0, None, type(e).__name__

    head = raw[:2000].lower()
    if "<rss" in head or "<feed" in head or "<rdf" in head:
        items = len(re.findall(r"<item[\s>]", raw)) + len(re.findall(r"<entry[\s>]", raw))
    else:
        items = 0
    newest = None
    for pat in (r"<pubDate>([^<]+)</pubDate>", r"<updated>([^<]+)</updated>",
                r"<published>([^<]+)</published>", r"<dc:date>([^<]+)</dc:date>"):
        hits = re.findall(pat, raw[:400000])
        if hits:
            try:
                d = parsedate_to_datetime(hits[0])
                if d.tzinfo is None:
                    d = d.replace(tzinfo=datetime.timezone.utc)
                newest = (datetime.datetime.now(datetime.timezone.utc) - d).days
                break
            except Exception:
                continue
    kind = "xml" if items else ("html" if "<html" in head else "other")
    return status, kind, items, newest, ""


def verdict(status, kind, items, age):
    if status == 0:
        return "dead"
    if status >= 400 or status == 0:
        return "dead"
    if items == 0:
        return "empty"
    if age is not None and age > STALE_DAYS:
        return "stale"
    return "alive"


def main():
    t0 = time.time()
    src = json.load(open(TARGETS, encoding="utf-8"))
    todo = [s for s in src if s.get("feed_url")]
    print("探活 %d 个 feed（共 %d 条源）" % (len(todo), len(src)), flush=True)

    def work(s):
        st, kind, n, age, err = fetch_feed(s["feed_url"])
        v = verdict(st, kind, n, age)
        return s["feed_url"], {"status": st, "kind": kind, "items": n,
                               "age_days": age, "verdict": v, "err": err}

    res = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for url, r in ex.map(work, todo):
            res[url] = r

    # 回写源清单（只改 last_probe* 三个字段）
    today = datetime.date.today().isoformat()
    for s in src:
        r = res.get(s.get("feed_url"))
        if not r:
            continue
        s["last_probe"] = today
        s["last_probe_status"] = r["verdict"]
        s["last_probe_items"] = r["items"]
    json.dump(src, open(TARGETS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    buckets = {}
    for url, r in res.items():
        buckets.setdefault(r["verdict"], []).append(url)
    summary = {
        "probed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_sources": len(src),
        "probed": len(todo),
        "counts": {k: len(v) for k, v in buckets.items()},
        "alive_but_stale": len(buckets.get("stale", [])),
        "secs": round(time.time() - t0, 1),
    }
    os.makedirs("data", exist_ok=True)
    json.dump(summary, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
