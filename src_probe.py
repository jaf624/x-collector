#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断v2：对比锚文本URL与pat链接URL，定位涉华预筛失效根因；并为0链接源找正确文章URL。"""
import os, re, ssl, json, urllib.request, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CN_RE = re.compile(r"(china|chinese|beijing|\bprc\b|\bccp\b|taiwan|taipei|hong\s?kong|xinjiang|tibet|"
                   r"uyghur|sino-|xi jinping|huawei|tiktok|bytedance|rare earth|mineral|cobalt|lithium|"
                   r"中国|北京|台海|台湾|香港|新疆|西藏|华为)", re.I)
WANT = ["日经亚洲-中国", "美贸易代表办公室-新闻稿", "美国能源部-新闻", "美国财政部-新闻稿",
        "USGS美国地质调查局-新闻", "Defense News防务新闻", "美军印太司令部-新闻", "白宫-声明与简报",
        "IEA国际能源署-新闻", "USNI海军学会新闻"]


def reader(url):
    req = urllib.request.Request("https://r.jina.ai/" + url,
                                 headers={"Authorization": "Bearer " + KEY, "Accept": "text/plain",
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return None, "EXC " + repr(e)[:160]


def norm(base, u):
    u = (u or "").strip()
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return "https:" + u
    if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", u):
        return "https://" + u
    if u.startswith("/"):
        p = urllib.parse.urlparse(base)
        return f"{p.scheme}://{p.netloc}{u}"
    return urllib.parse.urljoin(base, u)


cfg = json.load(open("targets/intel_sources.json", encoding="utf-8"))
secs = [s for s in cfg["sections"] if s.get("name") in WANT]
for s in secs:
    st, body = reader(s["url"])
    raw_links = re.findall(s["pat"], body)
    links = []
    for u in raw_links:
        u = norm(s["url"], u)
        if u not in links:
            links.append(u)
    anchors = []
    for m in re.finditer(r"\[([^\[\]]{6,200})\]\((https?://[^\s\)\]]+)\)", body):
        t, u = m.group(1).strip(), norm(s["url"], m.group(2).strip())
        if u and not t.startswith("http"):
            anchors.append((t, u))
    cn_anchors = [(t, u) for t, u in anchors if CN_RE.search(t)]
    lset = set(links)
    inset = [(t, u) for t, u in cn_anchors if u in lset]
    print("\n===== %s | pat链接%d 锚文本%d 涉华锚文本%d 涉华且命中pat%d" % (
        s["name"], len(links), len(anchors), len(cn_anchors), len(inset)))
    print("  pat链接样例:")
    for u in links[:3]:
        print("    L:", u[:110])
    print("  涉华锚文本样例:")
    for t, u in cn_anchors[:6]:
        print("    A[%s] %s" % ("命中" if u in lset else "不中", t[:50]), "=>", u[:80])
    if len(links) == 0:
        print("  --- 所有含news/article/press/statement的http链接 ---")
        cands = re.findall(r"https?://[^\s\)\]]+", body)
        seen = set()
        for u in cands:
            if re.search(r"(news|article|press|statement|briefing|release|stories|pr/)", u, re.I) and u not in seen:
                seen.add(u); print("    C:", u[:120])
                if len(seen) >= 12:
                    break
