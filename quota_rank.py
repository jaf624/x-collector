# -*- coding: utf-8 -*-
"""按 ROI 给源排队，并给"活但不出料"的源定处置（幂律：让 20% 的源吃掉 80% 的请求）。

输入：data/source_yield.json（每轮逐源账本：parsed/accepted/skip）
输出：data/source_quota.json（每源 ROI + 建议 + 连续空转次数）
可选 --apply：把连续 3 轮空转的源在 targets 里降到 C 级（不删除，源会复活）

ROI 口径：accepted / parsed —— 分母用"解析到的条数"而不是请求数，
因为一个源抓一次能解析 100 条，和抓 10 次各解析 10 条，不该同样计价。
"""
import argparse, json, os, time
from collections import defaultdict

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yld", default="data/source_yield.json")
    ap.add_argument("--targets", default="targets/institute_sources.json")
    ap.add_argument("--out", default="data/source_quota.json")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    y = json.load(open(a.yld, encoding="utf-8"))
    rounds = sorted(y)

    stat = defaultdict(lambda: {"runs": 0, "parsed": 0, "accepted": 0, "zero_streak": 0})
    for rk in rounds:
        rows = y[rk].get("rows") or []
        for r in rows:
            h = r.get("host")
            if not h:
                continue
            s = stat[h]
            s["runs"] += 1
            s["parsed"] += r.get("parsed", 0) or 0
            s["accepted"] += r.get("accepted", 0) or 0
        # 连续空转：按时间顺序累计
        cur_zero = {r.get("host") for r in rows if (r.get("parsed", 0) or 0) > 0 and (r.get("accepted", 0) or 0) == 0}
        for h, s in stat.items():
            if h in cur_zero:
                s["zero_streak"] = s["zero_streak"] + 1 if s.get("_last_zero") else 1
                s["_last_zero"] = True
            else:
                s["_last_zero"] = False
                if s["runs"]:
                    s["zero_streak"] = 0

    rows = []
    for h, s in stat.items():
        roi = (s["accepted"] / s["parsed"]) if s["parsed"] else 0.0
        if s["accepted"] == 0 and s["zero_streak"] >= 3:
            adv = "demote"
        elif roi >= 0.1:
            adv = "boost"
        elif s["accepted"] == 0:
            adv = "watch"
        else:
            adv = "keep"
        rows.append({"host": h, "runs": s["runs"], "parsed": s["parsed"],
                     "accepted": s["accepted"], "roi": round(roi, 4),
                     "zero_streak": s["zero_streak"], "advice": adv})

    rows.sort(key=lambda r: -r["roi"])
    n = len(rows)
    top20 = max(1, int(n * 0.2))
    agg = {k: sum(1 for r in rows if r["advice"] == k) for k in ("boost", "keep", "watch", "demote")}
    # 幂律体检：前 20% 源贡献了多少采纳
    acc_total = sum(r["accepted"] for r in rows) or 1
    top_acc = sum(r["accepted"] for r in rows[:top20])
    out = {"at": time.strftime("%Y-%m-%dT%H:%M"), "rounds": rounds[-6:], "sources": n,
           "advice": agg, "top20pct_share": round(top_acc / acc_total, 3), "rows": rows}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if a.apply:
        t = json.load(open(a.targets, encoding="utf-8"))
        dem = {r["host"] for r in rows if r["advice"] == "demote"}
        ch = 0
        for s in t:
            if s.get("host") in dem and s.get("grade") != "C":
                s["grade"] = "C"
                s["demoted_at"] = time.strftime("%Y-%m-%d")
                ch += 1
        json.dump(t, open(a.targets, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("降级源 %d 个" % ch, flush=True)

    print("源 %d｜boost %d｜keep %d｜watch %d｜demote %d｜前20%%源贡献采纳 %.1f%%"
          % (n, agg["boost"], agg["keep"], agg["watch"], agg["demote"],
             top_acc / acc_total * 100), flush=True)


if __name__ == "__main__":
    main()
