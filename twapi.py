#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TwitterAPI.io 主动采集器（海外 runner 定时运行）。
与免登录的 collect.py 互补：
  - collect.py : 免登录，按"用户投喂的推文ID"取数（免费、30分钟一次）
  - twapi.py   : 第三方数据接口，可"关键词搜索 + 指定账号时间线"主动发现
                （按量计费、极便宜，单独 workflow 每 6 小时一次以控制额度）
需要 GitHub Secret: TWAPI_IO_KEY （https://twitterapi.io 控制台获取）。
未配置 key 时正常退出（不报错），等配好再生效。
结果累积去重写入 data/x_feed.json，并把图片落地到 data/images（复用 collect 的逻辑）。
"""
import os, json, time, urllib.request, urllib.parse, urllib.error, datetime
import collect  # 复用 OUT / ROOT / read_lines / localize_media

KEY = os.environ.get("TWAPI_IO_KEY", "").strip()
BASE = "https://api.twitterapi.io"
PAGES_PER_TARGET = 1     # 每个账号/关键词抓几页（每页最多20条），控制按量费用
ONLY_IMAGES = True       # 提示词站主打"图文对应"，只收带图原创


def api(path, params, retries=2):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": KEY, "Accept": "application/json"})
    for k in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:200]
            print("[twapi] HTTP", e.code, body)
            if e.code in (401, 403):
                return None  # key 无效/欠费，不必重试
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(4 * (k + 1)); continue
            return None
        except Exception as e:
            print("[twapi] err", repr(e)[:120]); time.sleep(3 * (k + 1))
    return None


def parse_media(t):
    photos, video = [], ""
    medias = (t.get("extendedEntities") or {}).get("media") or t.get("media") or []
    for m in medias:
        typ = (m.get("type") or "").lower()
        oi = m.get("original_info") or m.get("originalInfo") or {}
        if typ == "photo" or m.get("media_url_https") or m.get("imageUrl"):
            u = m.get("media_url_https") or m.get("imageUrl") or m.get("url")
            if u:
                photos.append({"url": u, "w": oi.get("width") or m.get("width"),
                               "h": oi.get("height") or m.get("height")})
        elif typ in ("video", "animatedgif"):
            if m.get("videoUrl"):
                video = m["videoUrl"]
            else:
                vi = m.get("video_info") or m.get("videoInfo") or {}
                vs = vi.get("variants") or m.get("variants") or []
                mp4 = [v for v in vs if v.get("content_type") == v.get("contentType") == "video/mp4"
                       or v.get("content_type") == "video/mp4" or v.get("contentType") == "video/mp4"]
                if mp4:
                    video = sorted(mp4, key=lambda x: x.get("bitrate", 0))[-1].get("url", "")
    return photos, video


def to_rec(t):
    a = t.get("author") or {}
    tid = str(t.get("id") or "")
    photos, video = parse_media(t)
    return {
        "x_id": tid,
        "screen_name": a.get("userName") or "",
        "author": a.get("name") or "",
        "verified": bool(a.get("isBlueVerified") or a.get("isVerified") or a.get("verified")),
        "created_at": t.get("createdAt") or "",
        "text_raw": t.get("text") or "",
        "lang": t.get("lang") or "",
        "photos": photos,
        "video": video,
        "url": f"https://x.com/{a.get('userName','i')}/status/{tid}",
        "fav": t.get("likeCount", 0),
        "retweet": t.get("retweetCount", 0),
        "reply": t.get("replyCount", 0),
        "is_quote": bool(t.get("isQuote")),
        "fetched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def search(query, pages=PAGES_PER_TARGET):
    out, cursor = [], None
    for _ in range(pages):
        params = {"query": query, "queryType": "Latest"}
        if cursor:
            params["cursor"] = cursor
        d = api("/twitter/tweet/advanced_search", params)
        if not d:
            break
        for t in (d.get("tweets") or []):
            r = to_rec(t)
            if r["x_id"]:
                out.append(r)
        cursor = d.get("next_cursor")
        if not d.get("has_next_page") or not cursor:
            break
        time.sleep(1.2)
    return out


def main():
    if not KEY:
        print("[twapi] 未配置 TWAPI_IO_KEY secret，跳过主动采集（免登录 collect.py 仍正常）。")
        return 0

    accounts = collect.read_lines(collect.ROOT / "targets" / "accounts.txt")
    keywords = collect.read_lines(collect.ROOT / "targets" / "keywords.txt")
    img = " filter:images" if ONLY_IMAGES else ""
    recs = []

    for name in accounts:
        q = f"from:{name} -filter:retweets -filter:replies{img}"
        rs = search(q)
        recs += rs
        print(f"[twapi] @{name}: {len(rs)} 条")
        time.sleep(0.8)

    for kw in keywords:
        q = f"{kw} -filter:retweets -filter:replies{img}"
        rs = search(q)
        recs += rs
        print(f"[twapi] 关键词「{kw}」: {len(rs)} 条")
        time.sleep(0.8)

    # 图片落地到仓库（国内可达）
    collect.localize_media(recs)

    # 累积去重合并进同一个 feed
    old = {}
    if collect.OUT.exists():
        try:
            old = {x["x_id"]: x for x in json.loads(collect.OUT.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    for r in recs:
        if r.get("x_id"):
            old[r["x_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    collect.OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[twapi] 本次 {len(recs)} 条，feed 累积 {len(feed)} 条 -> {collect.OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
