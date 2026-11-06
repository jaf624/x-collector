# -*- coding: utf-8 -*-
"""诊断"解析到条目、但一条都没被采纳"的源：是过滤太严，还是源本身跑题。

判定口径（可回改）：
  hit = 标题/摘要里出现涉华或安全主题词
  desc_rate = 摘要有实质内容的条目占比
  分类：
    keep_strict  hit>=0.20 且采纳 0  → 有料被过滤掉了，要查过滤规则
    off_topic    hit<0.05            → 源跑题，应降 C 或移出采集
    partial      其余                → 部分对口，保留观察
输出只写聚合与哈希键，不打印源名。
"""
import argparse, hashlib, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netguard

CN = re.compile(r"中国|China|Chinese|Taiwan|台海|Beijing|PLA|rare earth|semiconductor|"
                r"chip|export control|sanction|tariff|naval|missile|drill|military|defense|"
                r"strateg|security|geopolit", re.I)


def items_of(body):
    if not body or len(body) < 200:
        return []
    blk = re.findall(r"<item[\s>][\s\S]*?</item>", body, re.I) or \
          re.findall(r"<entry[\s>][\s\S]*?</entry>", body, re.I)
    out = []
    for b in blk[:50]:
        t = re.search(r"<title[^>]*>([\s\S]*?)</title>", b, re.I)
        d = re.search(r"<(?:description|summary|content)[^>]*>([\s\S]*?)</", b, re.I)
        title = re.sub(r"<[^>]+>|<!\[CDATA\[|\]\]>", " ", t.group(1)).strip() if t else ""
        desc = re.sub(r"<[^>]+>|<!\[CDATA\[|\]\]>", " ", d.group(1)).strip() if d else ""
        if title:
            out.append((title, desc))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="targets/institute_sources.json")
    ap.add_argument("--yld", default="data/source_yield.json")
    ap.add_argument("--out", default="data/zero_yield_cause.json")
    ap.add_argument("--max", type=int, default=140)
    a = ap.parse_args()

    t = json.load(open(a.targets, encoding="utf-8"))
    feed = {s.get("host"): s.get("feed_url") for s in t}
    y = json.load(open(a.yld, encoding="utf-8"))
    last = sorted(y)[-1]
    rows = y[last]["rows"]
    zero = [r for r in rows if r.get("parsed", 0) > 0 and r.get("accepted", 0) == 0][: a.max]

    out, agg = [], {"keep_strict": 0, "partial": 0, "off_topic": 0, "unreachable": 0}
    for r in zero:
        h = r["host"]
        u = feed.get(h)
        rec = {"host": h, "k": hashlib.md5(h.encode()).hexdigest()[:10], "parsed": r.get("parsed", 0)}
        if not u:
            rec["cause"] = "no_feed"
            agg["unreachable"] += 1
            out.append(rec)
            continue
        st, body, _ = netguard.fetch(u, timeout=15)
        its = items_of(body) if st == 200 else []
        if not its:
            rec["cause"] = "unreachable"
            agg["unreachable"] += 1
            out.append(rec)
            continue
        hits = sum(1 for x, d in its if CN.search(x + " " + d))
        dr = sum(1 for _, d in its if len(d) > 100) / len(its)
        hr = hits / len(its)
        cause = "keep_strict" if hr >= 0.20 else ("off_topic" if hr < 0.05 else "partial")
        agg[cause] += 1
        rec.update({"n": len(its), "hit_rate": round(hr, 3),
                    "desc_rate": round(dr, 3), "cause": cause})
        out.append(rec)

    # 回写源清单：命中率≥0.2 的源标记 probe_hit_rate，采集器据此走"硬主题旁路"
    hit = {}
    for rec in out:
        if rec.get("hit_rate") is not None and rec.get("n"):
            hit[rec["host"]] = rec["hit_rate"]
    for s in t:
        h = s.get("host")
        if h in hit:
            s["probe_hit_rate"] = hit[h]
            s["last_diag"] = time.strftime("%Y-%m-%d")
    json.dump(t, open(a.targets, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"at": time.strftime("%Y-%m-%dT%H:%M"), "round": last,
               "zero_sources": len(rows) - sum(1 for r in rows if r.get("accepted", 0) > 0),
               "sampled": len(zero), "agg": agg, "rows": out},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("轮次 %s 抽样 %d 条 0 采纳源 → %s" % (last, len(zero), agg), flush=True)


if __name__ == "__main__":
    main()
