#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""body_backfill.py — 采集节点（GitHub Actions）正文回填（纯代码，无模型）

背景：data/intel_feed.json 里长年有 80% 条目正文为空或 <200 字（body_from=full 但 Jina 抓不到），
这些条目到服务器后只能套标题模板，是"料进去了产不出稿"的上游根因。
本脚本在采集节点运行（节点出网正常），直接打开出版社 URL 抽取正文，零 token、零模型。

判定（三重校验，防止把站点样板当正文）：
  1) 结构：优先 <article>/<main>，只保留最长段落（≥200 字）及其前后各 2 段；
  2) 噪声：导航行、机翻残渣、站点样板说明整行剔除；
  3) 相关性：标题词在正文命中 ≥2；事实句 ≥2。

用法：python3 body_backfill.py [--max 80] [--dry]
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")
try:
    from body_extract import extract
except Exception:
    extract = None
try:
    from gnews_resolve import resolve as gnews_resolve
except Exception:
    gnews_resolve = None

FEED = "data/intel_feed.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
SKIP_HOST = ("news.google.com", "googleusercontent", "federalregister.gov", "govinfo.gov")
TIMEOUT = 15
MAX_BYTES = 900_000


def norm(u):
    u = (u or "").strip()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"[?&](utm_[^=&]+|fbclid|gclid|spm)=[^&]*", "", u)
    return u.rstrip("?&")


def fetch_text(url, title):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                              "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read(MAX_BYTES).decode("utf-8", "ignore")
    txt, why = extract(raw, title)
    return (txt if txt else None), why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if not extract:
        print("body_extract 不可用，退出")
        return 1
    items = json.load(open(FEED, encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", [])

    todo = [x for x in items
            if len((x.get("content") or "").strip()) < 200
            and (x.get("url") or "").startswith("http")
            and not any(h in x.get("url", "") for h in SKIP_HOST)]
    gnews = [x for x in items
             if len((x.get("content") or "").strip()) < 200
             and "news.google.com" in (x.get("url") or "")]
    print("google-news 待还原=%d" % len(gnews), flush=True)
    print("feed=%d 待补=%d(含gnews) 取=%d" % (len(items), len(todo) + len(gnews), min(a.max, len(todo) + len(gnews))), flush=True)
    if a.dry:
        return 0

    batch = (todo + gnews)[: a.max]
    ok = fail = 0
    reasons = {}
    started = time.time()

    resolved = [0]

    def work(x):
        try:
            u = x.get("url") or ""
            if "news.google.com" in u:
                real = gnews_resolve(u) if gnews_resolve else None
                if not real:
                    return x, None, "gnews_unresolved"
                x["url_real"] = real
                u = real
            txt, why = fetch_text(norm(u), x.get("title") or "")
            return x, txt, why
        except Exception as e:
            return x, None, str(e)[:40]

    with ThreadPoolExecutor(max_workers=6) as ex:
        for fut in as_completed([ex.submit(work, x) for x in batch]):
            x, txt, why = fut.result()
            if not txt:
                fail += 1
                k = (why or "unknown").split(":")[0][:20]
                reasons[k] = reasons.get(k, 0) + 1
                continue
            x["content"] = txt
            x["body_from"] = "direct"
            if x.get("url_real"):
                resolved[0] += 1
            x["summary"] = ((x.get("title") or "") + "。" + txt[:160])[:400]
            x["needs_deepdive"] = False
            ok += 1

    json.dump(items, open(FEED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    remain = sum(1 for x in items if len((x.get("content") or "").strip()) < 200)
    stats = {"feed": len(items), "todo": len(todo), "ok": ok, "fail": fail,
             "reasons": reasons, "resolved": resolved[0], "remain_empty": remain, "secs": round(time.time() - started, 1),
             "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(stats, open("data/body_backfill_stats.json", "w"), ensure_ascii=False, indent=1)
    print("backfill ok=%d fail=%d 剩余空壳=%d/%d 原因=%s" % (ok, fail, remain, len(items), reasons), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
