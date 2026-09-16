#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jina 免费 API 主动发现 X 推文 -> syndication 取全文/图 -> 累积入库。

为什么需要它：GitHub Actions 是数据中心 IP，Bing/DDG/SearXNG/Reddit/匿名 Jina
对 X 一律限流或封 IP；Jina 搜索/代抓由 Jina 海外节点完成，带免费 API key 即可绕开。
- 发现：GET https://s.jina.ai/{query}  (Authorization: Bearer JINA_KEY, Accept: json)
- 取文：仍用 collect.fetch_by_id（syndication 免登录、结构化、图文对应，已验证）
免费 key：jina.ai 注册即送 1000 万 tokens、免信用卡；Search 100 RPM。
"""
import os, re, json, time, urllib.parse, urllib.request, urllib.error, ssl, datetime
import collect as C

KEY = os.environ.get("JINA_KEY", "").strip()
ID_RE = re.compile(r'(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status(?:es)?/(\d{10,})')
SEEN_F = C.OUT_DIR / "discovered_ids.json"
MAX_FETCH = int(os.environ.get("JINA_MAX", "60"))
NUM = os.environ.get("JINA_NUM", "3")  # 每次搜索返回条数（num 越小越省 token，实测 num=3≈1万token/次）
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def jina_search(query, timeout=45):
    """返回该查询命中的 {tweet_id: screen_name}。"""
    url = "https://s.jina.ai/" + urllib.parse.quote(query) + f"?num={NUM}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
        "User-Agent": C.UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        print(f"[jina-search] HTTP {e.code} {query[:40]} :: {e.read().decode('utf-8','ignore')[:120]}", flush=True)
        return {}
    except Exception as e:
        print(f"[jina-search] fail {query[:40]} :: {str(e)[:100]}", flush=True)
        return {}
    got = {}
    for it in d.get("data", []) or []:
        blob = f"{it.get('url','')} {it.get('content','')}"
        for sn, tid in ID_RE.findall(blob):
            got[tid] = sn
    return got


def load_seen():
    seen = set()
    if C.OUT.exists():
        try:
            seen = {x["x_id"] for x in json.loads(C.OUT.read_text(encoding="utf-8")) if x.get("x_id")}
        except Exception:
            pass
    if SEEN_F.exists():
        try:
            seen |= set(json.loads(SEEN_F.read_text(encoding="utf-8")))
        except Exception:
            pass
    return seen


def main():
    if not KEY:
        print("[jina] 未配置 JINA_KEY（GitHub Secret），跳过。注册免费 key：https://jina.ai/ -> API Keys（免信用卡）")
        return

    accounts = C.read_lines(C.ROOT / "targets" / "accounts.txt")
    keywords = C.read_lines(C.ROOT / "targets" / "keywords.txt")
    # (查询, 期望博主)；博主时间线每轮都跑；关键词广撒网仅 UTC 0/12 点跑（每天2次）以省 token
    import datetime
    h = datetime.datetime.utcnow().hour
    queries = [(f"site:x.com/{a}/status", a.lower()) for a in accounts]
    if h in (0, 12):
        queries += [(f"{k} site:x.com", None) for k in keywords]
    else:
        print(f"[jina] UTC {h} 点：本轮仅跑 {len(accounts)} 个博主时间线（关键词每天 UTC 0/12 点各一轮）", flush=True)

    found, seen = {}, load_seen()   # found[tid] = 期望博主（None=关键词发现）
    for i, (q, expect) in enumerate(queries):
        got = jina_search(q)
        for tid, sn in got.items():
            if tid not in found or found[tid] is None:
                found[tid] = expect
        print(f"[jina {i+1}/{len(queries)}] {q[:42]} -> 命中 {len(got)}（累计候选 {len(found)}）", flush=True)
        time.sleep(1.2)  # 远低于 100 RPM

    new_ids = [(tid, u) for tid, u in found.items() if tid not in seen]
    print(f"[jina] 候选 {len(found)}，去重后新 ID {len(new_ids)}，本轮取前 {min(MAX_FETCH,len(new_ids))}", flush=True)

    def keep(r, expect):
        """只留原创：剔除转推(RT)、纯回复(@开头)；博主时间线额外限定本人。"""
        txt = (r.get("text_raw") or "").lstrip()
        sn = (r.get("screen_name") or "").lower()
        if not sn or txt.startswith("RT ") or txt.startswith("@"):
            return False
        return (sn == expect.lower()) if expect else True

    recs, dropped = [], 0
    for tid, expect in new_ids[:MAX_FETCH]:
        r = C.fetch_by_id(tid)
        if r and r.get("text_raw") and keep(r, expect):
            recs.append(r)
            print("  [取到]", tid, r.get("screen_name"), (r.get("text_raw", "")[:40] or "").replace("\n", " "), flush=True)
        else:
            dropped += 1
            print("  [过滤/miss]", tid, (r or {}).get("screen_name", "-"), flush=True)
        time.sleep(1.0)
    print(f"[jina] 入库 {len(recs)}，过滤/未取到 {dropped}", flush=True)

    C.localize_media(recs)

    old = {}
    if C.OUT.exists():
        try:
            old = {x["x_id"]: x for x in json.loads(C.OUT.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    for r in recs:
        if r.get("x_id"):
            old[r["x_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    C.OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")

    all_seen = seen | set(found.keys())
    SEEN_F.write_text(json.dumps(sorted(all_seen), ensure_ascii=False), encoding="utf-8")
    print(f"[jina] 完成：取 {len(recs)}，新增 {len(recs)}，feed 累积 {len(feed)}", flush=True)


if __name__ == "__main__":
    main()
