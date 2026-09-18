#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发现器通道自测（不写库、不存正文、不下载媒体）：
境外节点经公开搜索引擎(DDG/Bing，直连->Jina)按 涉华+风险 关键词检索 t.me 公开频道，
再逐个验证 t.me/s/<name> 不登录可打开、近期涉华风险命中情况。只打印频道级统计，不打印正文。"""
import os, re, ssl, html, time, json, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BLOCK = {"telegram", "s", "share", "joinchat", "addstickers", "addtheme", "addemoji", "login",
         "proxy", "socks", "settings", "premium", "username", "durov", "telegramtalk", "auth",
         "stickers", "giftcode", "invoice", "wallet", "buy", "stars"}
CHINA = re.compile(r"(?i)china|chinese|ccp|prc|beijing|taiwan|hong kong|xinjiang|tibet|中国|中共|北京|台湾|香港|新疆|西藏|台海|解放军|习近平")
RISK = re.compile(r"(?i)protest|rally|regime|human rights|deepfake|independence|sanctions|leak|ransomware|bot network|exile|"
                  r"集会|抗议|台独|港独|疆独|藏独|深度伪造|制裁|数据泄露|流亡|民主|自由")
QUERIES = [
    'site:t.me (China OR Chinese OR CCP) (protest OR "human rights" OR regime)',
    'site:t.me Taiwan OR Tibet OR Xinjiang (independence OR exile OR rally)',
    'site:t.me 中国 OR 中共 (抗议 OR 自由 OR 民主 OR 制裁)',
]


def get(url, headers=None, timeout=45):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:
        return None, "EXC " + repr(e)[:120]


def search(q):
    enc = urllib.parse.quote(q)
    for label, u in [
        ("DDG直连", f"https://html.duckduckgo.com/html/?q={enc}"),
        ("Jina-DDG", f"https://r.jina.ai/https://html.duckduckgo.com/html/?q={enc}"),
        ("Jina-Bing", f"https://r.jina.ai/https://www.bing.com/search?q={enc}&setlang=en"),
    ]:
        hdr = {"Authorization": f"Bearer {KEY}"} if label.startswith("Jina") else None
        st, body = get(u, hdr, timeout=70)
        names = extract(body)
        print(f"  [{label}] HTTP{st} len={len(body)} 频道候选={len(names)}", flush=True)
        if names:
            return names, label
    return [], "none"


def extract(body):
    out = set()
    for m in re.finditer(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})", body):
        n = m.group(1)
        if n.lower() in BLOCK or n.isdigit():
            continue
        out.add(n)
    return out


def strip_html(t):
    t = re.sub(r"(?i)<br\s*/?>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def verify(name):
    st, body = get(f"https://t.me/s/{name}", timeout=30)
    if st != 200:
        return None
    title = ""
    mt = re.search(r'property="og:title" content="([^"]+)"', body)
    if mt:
        title = html.unescape(mt.group(1))
    posts = len(re.findall(r'data-post="' + re.escape(name) + r'/\d+"', body))
    dates = re.findall(r'datetime="(20\d\d-\d\d-\d\d)', body)
    # 只取文本块做计数，不落盘不打印
    texts = re.findall(r"tgme_widget_message_text[^>]*>(.*?)</div>", body, re.S)
    alltext = " ".join(strip_html(x) for x in texts)
    c = len(CHINA.findall(alltext)); r = len(RISK.findall(alltext))
    return {"name": name, "title": title[:42], "posts": posts, "china": c, "risk": r,
            "latest": max(dates) if dates else "?"}


def main():
    cand = {}
    for q in QUERIES:
        print(f"QUERY: {q}", flush=True)
        names, via = search(q)
        for n in names:
            cand[n] = via
        time.sleep(1)
    print(f"\n去重后候选频道总数: {len(cand)}；抽样验证最多 10 个（只统计，不存正文）", flush=True)
    rel = 0
    for name in list(cand)[:10]:
        v = verify(name)
        if not v:
            print(f"  - {name}: 非公开/打不开", flush=True); continue
        star = "★相关" if v["china"] > 0 and v["risk"] > 0 else ""
        if star:
            rel += 1
        print(f"  {star} {name} | {v['title']} | 近页{v['posts']}条 涉华{v['china']} 风险{v['risk']} 最近{v['latest']}", flush=True)
        time.sleep(0.4)
    print(f"\nDISCOVER_PROBE_DONE 候选{len(cand)} 相关{rel}")


if __name__ == "__main__":
    main()
