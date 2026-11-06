# -*- coding: utf-8 -*-
"""从 GitHub 开源 RSS 清单里扩源（纯代码、零 token、零 API 额度）。

为什么这么干：GitHub 上的 awesome-list 是全世界志愿者长期维护的"源目录"，
它本身就是免费、可校验、可持续更新的源仓库。把它当"发现层"，
比我们逐个站猜 feed 路径便宜一个数量级。

用法：
    python3 expand_sources.py _repo_lists/awesome_rss.md \
        --existing targets/institute_sources.json --out data/new_sources.json

筛选逻辑（三层，全部可回改）：
  1. 只收"能被判定为 feed 的 URL"（含 /feed、/rss、.xml、atom、feeds/posts）；
  2. 按 README 的章节标题给候选打主题标签（news/world/politics/tech/business/...）；
  3. 与已有源清单按域名去重；命中"高价值主题词"的候选单独置顶。
"""
import argparse, json, os, re, sys

TOPIC_WORDS = {
    "geopolitics": ["geopolit", "foreign", "diplom", "world", "international", "global"],
    "defense": ["defen", "military", "army", "navy", "war", "security", "strateg"],
    "econ": ["econom", "business", "finance", "market", "trade"],
    "tech": ["tech", "cyber", "ai", "semiconductor", "chip"],
    "energy": ["energy", "oil", "mining", "resource", "nuclear"],
    "china": ["china", "chinese", "asia", "taiwan", "hong kong"],
}

DROP_WORDS = ["celebrity", "gossip", "fashion", "beauty", "food", "recipe", "travel",
              "sport", "football", "movie", "music", "comic", "anime", "game", "crypto"]


def norm_host(u):
    m = re.match(r"https?://([^/]+)", u or "")
    return (m.group(1) if m else "").lower().replace("www.", "")


def looks_feed(u):
    ul = u.lower()
    return any(k in ul for k in ("/feed", "/rss", ".xml", "atom", "/?feed=", "feeds/posts"))


def sections(md):
    """把 markdown 切成 (章节标题, 段落文本)，用于给 URL 打主题标签。"""
    out, cur, buf = [], "root", []
    for line in md.splitlines():
        if re.match(r"^#{1,4}\s", line):
            if buf:
                out.append((cur, "\n".join(buf)))
                buf = []
            cur = re.sub(r"^#+\s*", "", line).strip().lower()
        else:
            buf.append(line)
    if buf:
        out.append((cur, "\n".join(buf)))
    return out


def label_for(text):
    t = text.lower()
    for k, words in TOPIC_WORDS.items():
        if any(w in t for w in words):
            return k
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lists", nargs="+", help="README / markdown 清单")
    ap.add_argument("--existing", default="", help="已有源清单 json，按域名去重")
    ap.add_argument("--out", default="data/new_sources.json")
    a = ap.parse_args()

    hosts = set()
    if a.existing and os.path.exists(a.existing):
        for s in json.load(open(a.existing, encoding="utf-8")):
            h = (s.get("host") or norm_host(s.get("base") or ""))
            if h:
                hosts.add(h)

    seen, rows = set(), []
    for path in a.lists:
        md = open(path, encoding="utf-8", errors="ignore").read()
        for title, body in sections(md):
            lab = label_for(title + " " + body[:400])
            for u in re.findall(r"https?://[^\s\)\]\|<>\"']+", body):
                u = u.rstrip(".,;:")
                if not looks_feed(u):
                    continue
                h = norm_host(u)
                if not h or h in seen:
                    continue
                low = (h + u).lower()
                if any(w in title.lower() for w in DROP_WORDS):
                    continue
                seen.add(h)
                rows.append({"host": h, "feed": u, "topic": lab,
                             "in_catalog": h in hosts})

    rows.sort(key=lambda r: (not r["in_catalog"], r["topic"] != "other", r["topic"], r["host"]))
    new_rows = [r for r in rows if not r["in_catalog"]]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"total": len(rows), "new": len(new_rows), "rows": rows},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    from collections import Counter
    print("候选 feed：%d，其中新域名 %d（已在清单 %d）" %
          (len(rows), len(new_rows), len(rows) - len(new_rows)))
    print("主题分布", Counter(r["topic"] for r in new_rows).most_common())


if __name__ == "__main__":
    main()
