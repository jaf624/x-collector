# -*- coding: utf-8 -*-
"""机构源定向扩源：从"泛媒体"转向"主题对口"。

上一轮实测（GitHub awesome-list 525 个候选）：227 个活的、3699 条条目，
但涉华/安全命中率只有 2.1%——说明泛媒体源只扩量、不扩料。

这份清单走另一条路：只收对口的机构站（智库/防务/能源矿产/监管/涉华媒体），
用 <link rel=alternate> + 常见路径自动发现其 feed，再实测条目数与涉华命中率。
结果按命中率分三档：S(≥30%) / A(10-30%) / B(<10%)，只有 S/A 直接进采集清单。

用法：python3 seed_institutions.py --out data/institutional_feeds.json
"""
import argparse, json, os, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netguard

# 主题对口机构（base 域名，不需要 feed 路径——由发现器自己找）
SEEDS = [
    # 智库（涉华/战略）
    "https://www.csis.org", "https://www.brookings.edu", "https://www.cfr.org",
    "https://www.rand.org", "https://www.stimson.org", "https://jamestown.org",
    "https://carnegieendowment.org", "https://www.atlanticcouncil.org",
    "https://www.cnas.org", "https://www.hudson.org", "https://www.fpri.org",
    "https://www.wilsoncenter.org", "https://www.chathamhouse.org", "https://www.iiss.org",
    "https://ecfr.eu", "https://merics.org", "https://www.lowyinstitute.org",
    "https://www.aspistrategist.org.au", "https://www.orfonline.org",
    # 防务
    "https://news.usni.org", "https://www.defensenews.com", "https://breakingdefense.com",
    "https://thedefensepost.com", "https://www.militarytimes.com", "https://warontherocks.com",
    "https://www.defense.gov", "https://www.nato.int", "https://www.army.mil",
    # 能源 / 矿产 / 供应链
    "https://www.mining.com", "https://www.mining-technology.com", "https://www.iea.org",
    "https://www.eia.gov", "https://www.world-nuclear-news.org", "https://oilprice.com",
    "https://www.kitco.com", "https://www.usgs.gov",
    # 经济 / 金融监管
    "https://www.imf.org", "https://www.worldbank.org", "https://www.oecd.org",
    "https://www.federalreserve.gov", "https://www.ecb.europa.eu", "https://www.bis.org",
    "https://home.treasury.gov", "https://www.commerce.gov",
    # 涉华媒体 / 区域
    "https://www.scmp.com", "https://focustaiwan.tw", "https://taiwannews.com.tw",
    "https://www3.nhk.or.jp", "https://asia.nikkei.com", "https://thediplomat.com",
    "https://www.straitstimes.com", "https://www.channelnewsasia.com",
    # 中国官方与半官方（合规可引）
    "https://www.mofcom.gov.cn", "https://www.mfa.gov.cn", "https://www.ndrc.gov.cn",
]

PATHS = ["/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/news/feed",
         "/?feed=rss2", "/feeds/posts/default", "/en/feed", "/feed/", "/rss/"]
CN = re.compile(r"中国|China|Chinese|Taiwan|台海|Beijing|PLA|稀土|rare earth|semiconductor|"
                r"chip|export control|sanction|tariff|naval|missile|drill", re.I)


def feed_from_html(base, html):
    for m in re.finditer(r'<link[^>]+>', html, re.I):
        tag = m.group(0).lower()
        if not any(k in tag for k in ("rss", "atom", "xml")):
            continue
        hm = re.search(r'href=["\']([^"\']+)', tag)
        if not hm:
            continue
        u = hm.group(1)
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = re.sub(r"(https?://[^/]+).*", r"\1", base) + u
        elif not u.startswith("http"):
            continue
        return u
    return ""


def items_of(body):
    if not body or len(body) < 200:
        return []
    blk = re.findall(r"<item[\s>][\s\S]*?</item>", body, re.I) or \
          re.findall(r"<entry[\s>][\s\S]*?</entry>", body, re.I)
    out = []
    for b in blk[:40]:
        t = re.search(r"<title[^>]*>([\s\S]*?)</title>", b, re.I)
        d = re.search(r"<(?:description|summary|content)[^>]*>([\s\S]*?)</", b, re.I)
        title = re.sub(r"<[^>]+>|<!\[CDATA\[|\]\]>", " ", t.group(1)).strip() if t else ""
        desc = re.sub(r"<[^>]+>|<!\[CDATA\[|\]\]>", " ", d.group(1)).strip() if d else ""
        if title:
            out.append((title, desc))
    return out


def probe(base):
    """1) 读首页找 <link rel=alternate>；2) 不行就试固定路径；只认 ≥3 条的结果。"""
    st, html, _ = netguard.fetch(base, timeout=15)
    url = feed_from_html(base, html) if (st == 200 and html) else ""
    if url:
        its = items_of(netguard.fetch(url, timeout=12)[1])
        if len(its) >= 3:
            hits = sum(1 for t, d in its if CN.search(t + " " + d))
            return {"base": base, "feed": url, "items": len(its), "hits": hits,
                    "hit_rate": round(hits / len(its), 3)}
    root = base.rstrip("/")
    for p in PATHS:
        cand = root + p
        its = items_of(netguard.fetch(cand, timeout=12)[1])
        if len(its) >= 3:
            hits = sum(1 for t, d in its if CN.search(t + " " + d))
            return {"base": base, "feed": cand, "items": len(its), "hits": hits,
                    "hit_rate": round(hits / len(its), 3)}
    return {"base": base, "feed": "", "items": 0, "hits": 0, "hit_rate": 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/institutional_feeds.json")
    a = ap.parse_args()
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(probe, SEEDS):
            rows.append(r)
            print("%-38s items=%-3d hits=%-2d %s" %
                  (r["base"][:38], r["items"], r["hits"], "OK" if r["feed"] else "-"), flush=True)
    for r in rows:
        r["tier"] = "S" if r["hit_rate"] >= 0.3 else ("A" if r["hit_rate"] >= 0.1 else "B")
    alive = [r for r in rows if r["feed"] and r["items"] >= 3]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"at": time.strftime("%Y-%m-%dT%H:%M"), "probed": len(rows),
               "alive": len(alive), "rows": rows},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("探活 %d / 活 %d / 分档 %s" % (len(rows), len(alive),
                                    dict(Counter(r["tier"] for r in alive))), flush=True)


if __name__ == "__main__":
    main()
