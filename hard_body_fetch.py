# -*- coding: utf-8 -*-
"""为 intel_feed 中缺正文的硬料，用 r.jina.ai 抓文章正文，写回 content/summary。
新增独立脚本，不改动现有 collect/translate 逻辑。"""
import json, os, re, time, urllib.request, ssl

KEY = os.environ.get("JINA_KEY", "").strip()
CAP = int(os.environ.get("INTEL_BODY_MAX", "40"))
PATH = "data/intel_feed.json"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

PRIO = re.compile(
    r"rare earth|critical mineral|lithium|cobalt|nickel|graphite|gallium|germanium|copper|"
    r"\boil\b|\bgas\b|\blng\b|crude|pipeline|tanker|strait|chokepoint|missile|deploy|warship|"
    r"naval|submarine|carrier|export control|entity list|semiconductor|\bchip\b|tariff|sanction|"
    r"nuclear|arms sale|稀土|锂|钴|镍|石墨|镓|锗|铜|石油|天然气|原油|管道|海峡|导弹|军舰|潜艇|"
    r"航母|出口管制|实体清单|半导体|芯片|关税|制裁|军售|关键矿产", re.I)


def fetch(url, timeout=50):
    req = urllib.request.Request("https://r.jina.ai/" + url, headers={
        "Authorization": f"Bearer {KEY}", "Accept": "text/plain", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        return resp.read().decode("utf-8", "ignore")


def clean(t):
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"[#>*`]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    if not KEY:
        print("[body] 无 JINA_KEY，跳过"); return
    feed = json.load(open(PATH, encoding="utf-8"))
    cand = [x for x in feed if not (x.get("content") or "").strip()
            and (x.get("url") or "").startswith("http")
            and PRIO.search(x.get("title") or "")]
    cand.sort(key=lambda x: x.get("published") or "", reverse=True)
    print("待补正文候选:", len(cand), flush=True)
    n = 0
    for x in cand:
        if n >= CAP:
            break
        u = x.get("url")
        try:
            body = clean(fetch(u))
            if len(body) < 120:
                print("  · empty", (x.get("title") or "")[:34], flush=True); continue
            x["content"] = body[:4000]
            x["summary"] = body[:240]
            x["body_from"] = "jina"
            n += 1
            print("  · ok", len(body), (x.get("title") or "")[:34], flush=True)
        except Exception as e:
            print("  · err", (x.get("title") or "")[:34], repr(e)[:80], flush=True)
        time.sleep(1.0)
    json.dump(feed, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("补正文完成:", n, flush=True)


if __name__ == "__main__":
    main()
