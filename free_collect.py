#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费、免登录主动采集（在 GitHub Actions 海外节点运行）：
  第一步：轮询存活的 Nitter 公开镜像，用其 RSS 抓「指定账号时间线 + 关键词搜索」，发现推文ID；
  第二步：用免登录 syndication 接口按ID补全正文、配图、视频（复用 collect.py）。
不花 API 费、不登录任何 X 账号、不触发账号风控。
输出累积去重到 data/x_feed.json，图片落地 data/images（国内可达）。
"""
import re, json, time, ssl, urllib.request, urllib.parse, pathlib
import collect

ROOT = pathlib.Path(__file__).resolve().parent
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# 公开 Nitter 兼容镜像（运行时自动探测存活，死的自动跳过；可随时增删）
# xcancel.com 为 Nitter 原作者维护的新官方站，置顶优先。
INSTANCES = [
    "xcancel.com", "nitter.lunar.icu", "nitter.privacyredirect.com", "nitter.foss.wtf",
    "nitter.tiekoetter.com", "nitter.salastil.com", "nitter.koyu.space", "tw.artemislena.eu",
    "nitter.services", "nitter.xbdm.net",
    "nitter.net", "nitter.poast.org", "nitter.privacydev.net", "nitter.woodland.cafe",
    "nitter.lucabased.xyz", "nitter.cz", "nitter.1d4.us", "nitter.kavin.rocks",
    "nitter.unixfox.eu", "nitter.fdn.fr", "nitter.qt", "nitter.pw", "nitter.tux.pizza",
    "nitter.opnxng.eu.org", "nitter.adminforge.de", "nitter.space", "nitter.relay.casa",
    "nitter.nohost.network", "lightbrd.com", "nitter.moomoo.me", "nitter.4o1o7.de",
    "nitter.dark.fail", "nitter.privacy.com.de", "n.coqu.eu",
]

def get(url, to=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=to, context=CTX) as r:
        return r.read()

def accounts():
    return collect.read_lines(ROOT / "targets" / "accounts.txt")

def keywords():
    return collect.read_lines(ROOT / "targets" / "keywords.txt")

def probe(probe_user):
    """返回最多2个能正常出账号RSS的存活实例。"""
    good = []
    for h in INSTANCES:
        try:
            b = get(f"https://{h}/{probe_user}/rss", 12)
            if b and (b"<rss" in b or b"<feed" in b or b"<?xml" in b):
                good.append(h); print("[alive]", h, flush=True)
                if len(good) >= 2:
                    break
        except Exception as e:
            print("[dead]", h, str(e)[:48], flush=True)
    return good

def ids_from_rss(url):
    try:
        b = get(url, 15).decode("utf-8", "ignore")
    except Exception as e:
        print("[rss fail]", url.split('?')[0], str(e)[:50], flush=True)
        return []
    ids, seen, out = [], set(), []
    for m in re.finditer(r"/status(?:es)?/(\d{10,})", b):
        ids.append(m.group(1))
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    return out

def main():
    acc = accounts(); kw = keywords()
    # 先自检免登录 syndication 按ID取推文是否可用（这是"手机投喂链接"兜底链路）
    probe_id = "2099762659071795585"
    try:
        sr = collect.fetch_by_id(probe_id)
        print("[syndication自检]", "OK @%s %s" % (sr["screen_name"], sr["text_raw"][:30]) if sr else "MISS", flush=True)
    except Exception as e:
        print("[syndication自检] 异常", str(e)[:80], flush=True)
    probe_user = acc[0] if acc else "voxcatai"
    print("探测存活 Nitter 实例（探针账号 %s）..." % probe_user, flush=True)
    insts = probe(probe_user)
    print("存活实例：", insts or "无", flush=True)

    idmap = {}  # tweet_id -> 来源
    # 1) 指定账号时间线
    for a in acc:
        got = []
        for h in insts:
            got = ids_from_rss(f"https://{h}/{a}/rss")
            if got:
                print(f"[user] {a} via {h}: {len(got)} 条", flush=True); break
            time.sleep(0.4)
        for i in got[:15]:
            idmap.setdefault(i, a)
        time.sleep(0.7)
    # 2) 关键词搜索（部分镜像开放搜索；不开放就跳过）
    for q in kw:
        qe = urllib.parse.quote(q)
        for h in insts:
            got = ids_from_rss(f"https://{h}/search/rss?f=tweets&q={qe}")
            if got:
                print(f"[search] {q} via {h}: {len(got)} 条", flush=True)
            for i in got[:10]:
                idmap.setdefault(i, "search:" + q)
            if got:
                break
            time.sleep(0.4)
        time.sleep(0.7)

    print("待 syndication 补全ID数：", len(idmap), flush=True)
    recs = []
    for n, (tid, via) in enumerate(idmap.items()):
        r = collect.fetch_by_id(tid)
        if r:
            recs.append(r)
        if (n + 1) % 20 == 0:
            print(f"补全进度 {n+1}/{len(idmap)}，成功 {len(recs)}", flush=True)
        time.sleep(0.7)

    collect.localize_media(recs)
    OUT = collect.OUT
    old = {}
    if OUT.exists():
        try:
            old = {x["x_id"]: x for x in json.loads(OUT.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    for r in recs:
        if r.get("x_id"):
            old[r["x_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：本次新抓 {len(recs)} 条，累积 {len(feed)} 条 -> {OUT}", flush=True)

if __name__ == "__main__":
    main()
