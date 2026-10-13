# -*- coding: utf-8 -*-
"""存量英文硬料独立补译：扫描 data/intel_feed.json，对可用、英文、硬新闻/机构源、
命中硬安全/资源/能源/军事主题且未翻译的条目，用 Google gtx 补中文；写回 feed 并重建 brief。
不跑 Jina 采集，几分钟完成，用于一次性打通存量硬料。"""
import json, os, re
import intel_collect as ic

ic.topic = re.compile(ic.TOPIC_RE, re.I)


def cn(s):
    return len(re.findall(r"[\u4e00-\u9fff]", s or ""))


def main():
    cap = int(os.environ.get("INTEL_MAX_TRANSLATE", "30"))
    path = "data/intel_feed.json"
    feed = json.load(open(path, encoding="utf-8"))
    n = 0
    for x in feed:
        if n >= cap:
            break
        try:
            if not x.get("usable") or x.get("machine_translated"):
                continue
            t = x.get("title", "") or ""
            body = x.get("content", "") or ""
            if cn(t + body[:300]) >= 8:
                continue
            if not (ic.is_hardnews_url(x.get("url", "")) or x.get("route") == "institute"):
                continue
            if ic.soft_news(t) or not ic.topic.search(t + " " + body[:2000]):
                continue
            zt = ic.gtx_translate(t)
            zs = ic.gtx_translate(re.sub(r"\s+", " ", body)[:600])
            zc = ic.gtx_translate(body[:3500])
            if zt:
                x["zh_title"] = zt
            if zs:
                x["summary"] = zs
            if zc:
                x["content"] = zc + "\n\n【原文 English Original】\n" + body
                x["machine_translated"] = True
                n += 1
                print("  · [译中] " + zt[:42], flush=True)
        except Exception:
            continue
    json.dump(feed, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 按 intel_collect 口径重建 brief（usable 子集，按质量分与发布时间降序）
    brief = sorted([x for x in feed if x.get("usable")],
                   key=lambda x: (x.get("quality_score", 0), x.get("published", "")), reverse=True)
    json.dump(brief, open("data/intel_brief.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("BACKFILL_DONE 补译 %d 篇；feed %d / brief %d" % (n, len(feed), len(brief)), flush=True)


if __name__ == "__main__":
    main()
