#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SocialData.tools 采集器（在 GitHub Actions 海外节点运行）。

定位：第三方 X 数据 API，由对方维护住宅代理池，海外 runner 直接 HTTPS 调用即可，
不需要 auth_token、不需要在数据中心登录 X、不怕机房 IP 被风控。
能力：关键词搜索（支持 X 高级搜索操作符）+ 指定博主时间线 + 单条/批量，含图文视频。

免费档限速 3 次/分钟 -> 本脚本强制每次调用间隔 21 秒；一轮约 26 次请求 ≈ 9 分钟。
认证：GitHub Secret  SOCIALDATA_KEY （Authorization: Bearer KEY）。未配置则优雅退出。

输出与 collect.py / free_collect.py 完全一致：累积去重写 data/x_feed.json，
图片落地 data/images（raw 地址，国内可达），供国内服务器洗练入库。
"""
import os, re, json, time, ssl, urllib.request, urllib.error, urllib.parse, datetime, pathlib
import collect

ROOT = pathlib.Path(__file__).resolve().parent
BASE = "https://api.socialdata.tools"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
MIN_INTERVAL = 21.0          # 免费档 3 req/min，留余量
PER_USER = 20                # 每个博主取首页条数（不翻页，靠每 3 小时一轮覆盖增量）
PER_SEARCH = 30
_last = [0.0]


def _throttle():
    dt = time.time() - _last[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last[0] = time.time()


def _req(method, path, key, payload=None, retry=3):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for k in range(retry + 1):
        _throttle()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (402,):
                print("[socialdata] 402 余额/免费额度不足：", body[:160], flush=True)
                return None
            if e.code in (403, 404):
                print("[socialdata] 跳过", path, e.code, body[:120], flush=True)
                return None
            print("[socialdata] HTTP", e.code, "第", k + 1, "次，退避", body[:120], flush=True)
            time.sleep(8 * (k + 1))
        except Exception as e:
            print("[socialdata] 异常", str(e)[:100], "第", k + 1, "次", flush=True)
            time.sleep(6 * (k + 1))
    return None


def _list(d, *keys):
    """从多种可能的响应壳里取出推文/用户数组。"""
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for kk in keys:
            v = d.get(kk)
            if isinstance(v, list):
                return v
        for v in d.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def normalize(t):
    """X 原生 tweet 对象 -> 统一 record（字段对齐 collect.normalize）。"""
    if not isinstance(t, dict):
        return None
    # 纯转推解包到原帖（提示词网站优先原创图文）
    rt = t.get("retweeted_status")
    if isinstance(rt, dict):
        t = rt
    u = t.get("user") or {}
    tid = str(t.get("id_str") or t.get("id") or "")
    if not tid or not tid.isdigit():
        return None
    media = []
    ext = t.get("extended_entities") or {}
    ent = t.get("entities") or {}
    media = ext.get("media") or ent.get("media") or []
    photos, video = [], ""
    for m in media:
        mt = m.get("type")
        if mt == "photo":
            w = h = None
            try:
                w = (m.get("original_info") or {}).get("width") or (m.get("sizes", {}).get("large", {}) or {}).get("w")
                h = (m.get("original_info") or {}).get("height") or (m.get("sizes", {}).get("large", {}) or {}).get("h")
            except Exception:
                pass
            photos.append({"url": m.get("media_url_https") or m.get("media_url"), "w": w, "h": h})
        elif mt in ("video", "animated_gif"):
            vs = (m.get("video_info") or {}).get("variants") or []
            mp4 = [v for v in vs if v.get("content_type") == "video/mp4"]
            if mp4 and not video:
                video = sorted(mp4, key=lambda x: x.get("bitrate", 0))[-1].get("url", "")
    text = t.get("full_text") or t.get("text") or ""
    screen = u.get("screen_name") or t.get("screen_name") or "i"
    return {
        "x_id": tid,
        "screen_name": screen,
        "author": u.get("name") or "",
        "verified": bool(u.get("verified") or u.get("is_blue_verified") or u.get("verified_type")),
        "created_at": t.get("tweet_created_at") or t.get("created_at") or "",
        "text_raw": text,
        "lang": t.get("lang") or "",
        "photos": photos,
        "video": video,
        "url": f"https://x.com/{screen}/status/{tid}",
        "fav": t.get("favorite_count", 0) or 0,
        "retweet": t.get("retweet_count", 0) or 0,
        "reply": t.get("reply_count", 0) or 0,
        "is_quote": bool(t.get("is_quote_status")),
        "fetched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def main():
    key = os.environ.get("SOCIALDATA_KEY", "").strip()
    if not key:
        print("[socialdata] 未配置 Secret SOCIALDATA_KEY，跳过（注册 socialdata.tools 后在 GitHub Secrets 配置即可）。", flush=True)
        return
    accounts = collect.read_lines(ROOT / "targets" / "accounts.txt")
    keywords = collect.read_lines(ROOT / "targets" / "keywords.txt")

    raw = []

    # 1) 用户名 -> user_id（一次批量请求，最多 100 个）
    uid_map = {}
    if accounts:
        d = _req("POST", "/twitter/users-by-usernames", key, {"usernames": accounts[:100]})
        for u in _list(d, "users", "data"):
            sn = u.get("screen_name")
            uid = u.get("id_str") or str(u.get("id") or "")
            if sn and uid:
                uid_map[sn.lower()] = uid
        print(f"[socialdata] 解析博主 {len(uid_map)}/{len(accounts)}：{list(uid_map.items())[:6]} ...", flush=True)

    # 2) 博主时间线
    for sn in accounts:
        uid = uid_map.get(sn.lower())
        if not uid:
            print("[socialdata] 无 user_id，跳过博主", sn, flush=True); continue
        d = _req("GET", f"/twitter/user/{uid}/tweets", key)
        if d is None:
            continue
        ts = _list(d, "tweets", "data")
        print(f"[socialdata][user] @{sn}: {len(ts)} 条", flush=True)
        raw.extend(ts[:PER_USER])

    # 3) 关键词搜索（Latest）
    for q in keywords:
        qs = urllib.parse.urlencode({"query": q, "type": "Latest"})
        d = _req("GET", f"/twitter/search?{qs}", key)
        if d is None:
            continue
        ts = _list(d, "tweets", "data")
        print(f"[socialdata][search] {q}: {len(ts)} 条", flush=True)
        raw.extend(ts[:PER_SEARCH])

    # 归一化 + 去噪（去纯 RT、去空文本）
    recs, seen = [], set()
    for t in raw:
        r = normalize(t)
        if not r or r["x_id"] in seen:
            continue
        if r["text_raw"].strip().startswith("RT @") and not r["photos"]:
            continue
        seen.add(r["x_id"]); recs.append(r)
    print(f"[socialdata] 本轮去重后有效推文 {len(recs)} 条，开始下图...", flush=True)

    collect.localize_media(recs)

    OUT = collect.OUT
    old = {}
    if OUT.exists():
        try:
            old = {x["x_id"]: x for x in json.loads(OUT.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    added = 0
    for r in recs:
        if r["x_id"] not in old:
            added += 1
        old[r["x_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[socialdata] 完成：本轮抓 {len(recs)}，新增 {added}，累积 {len(feed)} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
