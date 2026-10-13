#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性诊断：在美国 runner 上用 r.jina.ai 渲染新增硬新闻源，验证 pat 链接、锚文本[标题](url)、
以及锚文本能否用于涉华预筛。手动 workflow_dispatch 触发。"""
import os, re, ssl, json, urllib.request, urllib.error

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

CN_RE = re.compile(r"(china|chinese|beijing|\bprc\b|\bccp\b|taiwan|taipei|hong\s?kong|xinjiang|tibet|"
                   r"uyghur|sino-|xi jinping|huawei|tiktok|bytedance|rare earth|中国|北京|台海|台湾|"
                   r"香港|新疆|西藏|华为)", re.I)
WANT = ["日经亚洲-中国", "日经亚洲-商业", "美贸易代表办公室-新闻稿", "美工业与安全局BIS-新闻",
        "美国能源部-新闻", "美国国务院-新闻稿", "美国财政部-新闻稿", "白宫-声明与简报", "WTO-新闻",
        "欧盟贸易总署-新闻", "日本经产省METI-新闻", "USGS美国地质调查局-新闻", "Mining.com矿业资讯",
        "IEA国际能源署-新闻", "OilPrice能源资讯", "USNI海军学会新闻", "Defense News防务新闻",
        "美军印太司令部-新闻", "IMF国际货币基金组织-新闻"]


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
    if u.startswith("http"):
        return u.rstrip(".,;)")
    from urllib.parse import urljoin
    return urljoin(base, u).rstrip(".,;)")


cfg = json.load(open("targets/intel_sources.json", encoding="utf-8"))
secs = [s for s in cfg["sections"] if s.get("name") in WANT]
for s in secs:
    st, body = reader(s["url"])
    links = []
    for u in re.findall(s["pat"], body):
        u = norm(s["url"], u)
        if u not in links:
            links.append(u)
    # 锚文本
    anchors = {}
    for m in re.finditer(r"\[([^\[\]]{6,200})\]\((https?://[^\s\)\]]+)\)", body):
        t, u = m.group(1).strip(), norm(s["url"], m.group(2).strip())
        if u and u not in anchors and not t.startswith("http"):
            anchors[u] = t
    cn_hits = [(t, u) for u, t in anchors.items()
               if u in links and CN_RE.search(t)]
    print("\n===== %s | HTTP %s | pat链接%d 锚文本%d 锚文本命中pat且涉华%d" % (
        s["name"], st, len(links), len(anchors), len(cn_hits)))
    for t, u in cn_hits[:8]:
        print("   CN | %s | %s" % (t[:70], u[:78]))
    if len(links) == 0:
        print("   --- 0链接, 原始markdown前700字 ---")
        print("   " + body[:700].replace("\n", "\n   "))
