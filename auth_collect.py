#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录态主动采集（twikit 2.x 异步版），在 GitHub Actions 海外节点运行。
凭证来自 GitHub Secrets：X_AUTH_TOKEN（httpOnly 登录凭证）+ X_CT0（CSRF）。
不在机房走登录流程，因此不会触发 X 的“异地+机器人”登录验证；
带凭证只调内部接口，配合随机限速长期保号，主动抓「博主时间线 + 关键词搜索」。
输出累积去重到 data/x_feed.json，图片落地 data/images。
"""
import os, json, time, random, asyncio, datetime, pathlib
import collect
from twikit import Client

ROOT = pathlib.Path(__file__).resolve().parent
OUT = collect.OUT


def conv(t, via):
    photos, video = [], ""
    for m in (getattr(t, "media", None) or []):
        cls = m.__class__.__name__
        if cls == "Photo":
            photos.append({
                "url": getattr(m, "media_url", ""),
                "w": getattr(m, "width", None), "h": getattr(m, "height", None)})
        elif cls in ("Video", "AnimatedGif"):
            try:
                ss = [s for s in m.streams if (getattr(s, "content_type", "") or "").startswith("video")]
                if ss:
                    video = sorted(ss, key=lambda s: getattr(s, "bitrate", 0) or 0)[-1].url
            except Exception:
                pass
    u = getattr(t, "user", None)
    tid = str(getattr(t, "id", "") or "")
    return {
        "x_id": tid,
        "screen_name": (getattr(u, "screen_name", "") or via) if u else via,
        "author": getattr(u, "name", "") if u else "",
        "verified": bool(getattr(u, "verified", False)) if u else False,
        "created_at": str(getattr(t, "created_at", "") or ""),
        "text_raw": getattr(t, "text", "") or getattr(t, "full_text", "") or "",
        "lang": getattr(t, "lang", "") or "",
        "photos": photos,
        "video": video,
        "url": f"https://x.com/{getattr(u,'screen_name','i') if u else 'i'}/status/{tid}",
        "fav": getattr(t, "favorite_count", 0) or 0,
        "retweet": getattr(t, "retweet_count", 0) or 0,
        "reply": getattr(t, "reply_count", 0) or 0,
        "is_quote": bool(getattr(t, "is_quote_status", False)),
        "fetched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


async def main():
    at = os.environ.get("X_AUTH_TOKEN", "").strip()
    ct0 = os.environ.get("X_CT0", "").strip()
    if not at or not ct0:
        print("[AUTH] 未配置 X_AUTH_TOKEN / X_CT0 secret，跳过登录态采集。", flush=True)
        return

    c = Client(language="en-US")
    c.set_cookies({"auth_token": at, "ct0": ct0, "lang": "en"})

    acc = collect.read_lines(ROOT / "targets" / "accounts.txt")
    kw = collect.read_lines(ROOT / "targets" / "keywords.txt")

    # 登录态自检：能取到一个已知用户即视为凭证有效
    try:
        probe = await c.get_user_by_screen_name(acc[0] if acc else "voxcatai")
        print("[AUTH] 凭证有效，探针 @%s（%s）" % (
            getattr(probe, "screen_name", ""), getattr(probe, "name", "")), flush=True)
    except Exception as e:
        print("[AUTH-FAIL] 凭证无效/过期或被风控，需重新导出 auth_token：" + str(e)[:180], flush=True)
        return

    recs = []
    # 1) 博主时间线
    for a in acc:
        try:
            u = await c.get_user_by_screen_name(a)
            tweets = await u.get_tweets("Tweets", count=15)
            n0 = len(recs)
            for t in (tweets or []):
                try:
                    recs.append(conv(t, a))
                except Exception as ce:
                    print("[conv user]", a, str(ce)[:60], flush=True)
            print(f"[user] @{a}: +{len(recs)-n0}", flush=True)
        except Exception as e:
            print("[user fail]", a, str(e)[:100], flush=True)
        await asyncio.sleep(random.uniform(3.0, 6.0))

    # 2) 关键词搜索
    for q in kw:
        try:
            tweets = await c.search_tweet(q, "Latest", count=15)
            n0 = len(recs)
            for t in (tweets or []):
                try:
                    recs.append(conv(t, "search:" + q))
                except Exception as ce:
                    print("[conv search]", q, str(ce)[:60], flush=True)
            print(f"[search] {q}: +{len(recs)-n0}", flush=True)
        except Exception as e:
            print("[search fail]", q, str(e)[:100], flush=True)
        await asyncio.sleep(random.uniform(4.0, 7.0))

    print("本轮登录态采集条数：", len(recs), flush=True)
    collect.localize_media(recs)

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
    print(f"完成：本次 {len(recs)} 条，累积 {len(feed)} 条 -> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
