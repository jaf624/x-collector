#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发现器通道自测 v2（不写库、不存正文、不下载媒体）。
通道：s.jina.ai 搜索 -> DDG直连(还原uddg跳转/多重URL解码) -> Jina-Bing -> Jina-DDG。
只打印频道级统计，不打印正文。私群邀请链接(t.me/+、joinchat)天然排除。"""
import os, re, ssl, html, time, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("JINA_KEY", "").strip()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BLOCK = {"telegram", "s", "share", "joinchat", "addstickers", "addtheme", "addemoji", "login",
         "proxy", "socks", "settings", "premium", "username", "durov", "auth", "stickers",
         "giftcode", "invoice", "wallet", "buy", "stars", "android", "ios", "desktop", "web",
         "blog", "press", "tos", "privacy", "apps", "dl", "download"}
CHINA = re.compile(r"(?i)china|chinese|ccp|prc|beijing|taiwan|hong kong|xinjiang|tibet|中国|中共|北京|台湾|香港|新疆|西藏|台海|解放军|习近平")
RISK = re.compile(r"(?i)protest|rally|regime|human rights|deepfake|independence|sanctions|leak|ransomware|bot network|exile|dissident|"
                  r"集会|抗议|台独|港独|疆独|藏独|深度伪造|制裁|数据泄露|流亡|民主|自由|维权")
QUERIES = [
    "telegram channel t.me China Chinese human rights protests dissident",
    "telegram t.me channel Taiwan Tibet Xinjiang independence exile",
    "telegram t.me Chinese channel deepfake cognitive warfare sanctions leak",
    "telegram 频道 t.me 中国 维权 抗议 民主 自由",
]


def get(url, headers=None, timeout=60):
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


def extract(body):
    out = set()
    texts = [body]
    for m in re.finditer(r"uddg=([^&\"'<>]+)", body):
        texts.append(urllib.parse.unquote(m.group(1)))
    b = body
    for _ in range(3):
        d = urllib.parse.unquote(b)
        if d == b:
            break
        b = d
    texts.append(b)
    for t in texts:
        for m in re.finditer(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})", t):
            n = m.group(1)
            if n.lower() not in BLOCK and not n.isdigit():
                out.add(n)
    return out


def search(q):
    enc = urllib.parse.quote(q)
    attempts = [
        ("s.jina", f"https://s.jina.ai/{enc}", {"Authorization": f"Bearer {KEY}", "Accept": "text/plain"}),
        ("DDG直连", f"https://html.duckduckgo.com/html/?q={enc}", None),
        ("Jina-Bing", f"https://r.jina.ai/https://www.bing.com/search?q={enc}&setlang=en", {"Authorization": f"Bearer {KEY}"}),
        ("Jina-DDG", f"https://r.jina.ai/https://html.duckduckgo.com/html/?q={enc}", {"Authorization": f"Bearer {KEY}"}),
    ]
    for label, u, hdr in attempts:
        st, body = get(u, hdr, timeout=75)
        names = extract(body)
        print(f"  [{label}] HTTP{st} len={len(body)} 候选={len(names)}", flush=True)
        if names:
            return names, label
    return set(), "none"


def strip_html(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>", " ", t or "")))).strip()


def verify(name):
    st, body = get(f"https://t.me/s/{name}", timeout=30)
    if st != 200:
        return None
    mt = re.search(r'property="og:title" content="([^"]+)"', body)
    title = html.unescape(mt.group(1)) if mt else ""
    posts = len(re.findall(r'data-post="' + re.escape(name) + r'/\d+"', body))
    dates = re.findall(r'datetime="(20\d\d-\d\d-\d\d)', body)
    texts = re.findall(r"tgme_widget_message_text[^>]*>(.*?)</div>", body, re.S)
    alltext = " ".join(strip_html(x) for x in texts)
    return {"name": name, "title": title[:40], "posts": posts,
            "china": len(CHINA.findall(alltext)), "risk": len(RISK.findall(alltext)),
            "latest": max(dates) if dates else "?"}


def main():
    cand = {}
    for q in QUERIES:
        print(f"QUERY: {q}", flush=True)
        names, via = search(q)
        for n in names:
            cand[n] = via
        time.sleep(1.2)
    print(f"\n去重候选 {len(cand)}：{sorted(cand)[:30]}", flush=True)
    print("逐个公开验证（只统计不存正文），最多 15 个：", flush=True)
    rel = 0
    for name in sorted(cand)[:15]:
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
