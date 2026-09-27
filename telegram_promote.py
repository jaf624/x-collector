#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram 公开频道"审核转正/归档"脚本（可本地运行，也可由 Actions 每周运行）。

使用者已书面授权按客观阈值代为审核，所有决定写入配置与日志、全程留痕。
两级监测（合规红线不变：只抓 t.me/s 公开网页，不登录、不加入、不下载媒体）：
  - 一级 business_channels：原有锁定频道 + score>=45 或 recent3>=5（高分或活跃）；
  - 二级 watch_channels：score>=30 且最近45天内有更新（其余合格、低频观察）；
  - 归档 archived_channels：最近更新早于本年度1月1日（长期停更），
    或近7天/近3天零更新且 score<30（信号弱、留档备查）；
  - 其余维持 pending_review，不做处理。
"""
import os, json, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
CFG = os.path.join(ROOT, "targets", "telegram.json")
DISC = os.path.join(DATA, "tg_discovered.json")
LOG = os.path.join(DATA, "tg_promotions.json")

TIER1_SCORE = 45
TIER1_RECENT3 = 5
TIER2_SCORE = 30
FRESH_DAYS = 45
DEAD_CUTOFF = "2026-01-01"


def main():
    cfg = json.load(open(CFG, encoding="utf-8"))
    pool = json.load(open(DISC, encoding="utf-8")) if os.path.exists(DISC) else []

    # 模块四参数：窗口7天、3页、一级每频道50条、二级25条
    cfg["days"] = 7
    cfg["max_pages"] = 3
    cfg["max_per_channel"] = 50
    cfg["watch_max_per_channel"] = 25

    locked = [dict(c) for c in cfg.get("business_channels", [])]
    locked_names = {c["name"] for c in locked}
    cfg["business_channels"] = locked
    cfg["watch_channels"] = []
    arc = cfg.setdefault("archived_channels", [])
    arc_names = {c["name"] for c in arc}

    today = datetime.date.today()
    fresh_cut = (today - datetime.timedelta(days=FRESH_DAYS)).isoformat()
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    t1, t2, archived = [], [], []
    for x in pool:
        name, score = x.get("name", ""), x.get("score", 0)
        latest = x.get("latest", "")
        r7, r3 = x.get("recent7", 0), x.get("recent3", 0)
        alias = x.get("title", "") or name
        if name in locked_names:
            continue

        if latest and latest < DEAD_CUTOFF:
            reason, action = "频道长期停更，留档备查", "archive"
        elif r7 == 0 and r3 == 0 and score < TIER2_SCORE:
            reason, action = "近期无更新、信号弱，留档备查", "archive"
        elif latest and latest >= fresh_cut and (score >= TIER1_SCORE or r3 >= TIER1_RECENT3):
            reason, action = "高分或活跃，转正一级监测", "tier1"
        elif latest and latest >= fresh_cut and score >= TIER2_SCORE:
            reason, action = "分数达标，列入二级观察", "tier2"
        else:
            continue

        if action == "archive":
            if name not in arc_names:
                arc.append({"name": name, "alias": alias,
                            "reason": reason, "archived_at": today.isoformat()})
                arc_names.add(name)
            archived.append(name)
        elif action == "tier1":
            cfg["business_channels"].append({"name": name, "alias": alias})
            locked_names.add(name); t1.append(name)
        else:
            cfg["watch_channels"].append({"name": name, "alias": alias})
            t2.append(name)

    json.dump(cfg, open(CFG, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    log = []
    if os.path.exists(LOG):
        log = json.load(open(LOG, encoding="utf-8"))
    log.append({"ran_at": now, "tier1": t1, "tier2": t2, "archived": archived,
                "business_total": len(cfg["business_channels"]),
                "watch_total": len(cfg["watch_channels"]),
                "archived_total": len(arc)})
    json.dump(log, open(LOG, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("[promote] 一级+ %d：%s" % (len(t1), t1))
    print("[promote] 二级+ %d：%s" % (len(t2), t2))
    print("[promote] 归档 %d：%s" % (len(archived), archived))
    print("[promote] business=%d watch=%d archived=%d"
          % (len(cfg["business_channels"]), len(cfg["watch_channels"]), len(arc)))
    print("TG_PROMOTE_DONE")


if __name__ == "__main__":
    main()
