#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动发现引擎 v2: directory scan + auto-score + auto-add + codeword learning."""
import os, re, json, time, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
CFG = os.path.join(ROOT, "targets", "telegram.json")
OUT = os.path.join(DATA, "discover_v2.json")
KEY = os.environ.get("JINA_KEY", "").strip()

SEARCH_QUERIES = [
    "t.me tibet protest channel",
    "t.me uyghur human rights",
    "t.me hong kong protest",
    "t.me overseas chinese dissident",
    "t.me taiwan solidarity",
    "t.me religious persecution china",
    "t.me china human rights watch",
    "t.me chinese opposition movement",
]

DISCORD_TAGS = ["china", "tibet", "uyghur", "hongkong", "protest"]

BLOCK = {"telegram", "s", "share", "joinchat", "login", "settings", "blog", "press", "tos", "privacy"}

def jina_get(url):
    if not KEY: return ""
    jurl = "https://r.jina.ai/" + url
    req = urllib.request.Request(jurl, headers={"Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"Jina error: {e}")
        return ""

def extract_tg_channels(text):
    out = set()
    for m in re.finditer(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})", text):
        n = m.group(1)
        if n.lower() not in BLOCK and not n.isdigit():
            out.add(n)
    return out

def score_channel(title, desc):
    text = (title + " " + desc).lower()
    score = 0
    for kw in ["tibet", "uyghur", "hong kong", "taiwan", "china", "protest",
               "dissident", "human rights", "opposition", "freedom"]:
        if kw in text: score += 10
    for kw in ["chinese", "beijing", "activist", "movement"]:
        if kw in text: score += 3
    return score

def discover_tg():
    found = {}
    for q in SEARCH_QUERIES:
        print(f"search: {q}")
        text = jina_get(f"https://s.jina.ai/{urllib.parse.quote(q)}")
        channels = extract_tg_channels(text)
        for ch in channels:
            if ch not in found:
                preview = jina_get(f"https://t.me/s/{ch}")
                title = ""
                m = re.search(r'<meta property="og:title" content="([^"]+)"', preview)
                if m: title = m.group(1)
                desc = ""
                m = re.search(r'<meta property="og:description" content="([^"]+)"', preview)
                if m: desc = m.group(1)
                score = score_channel(title, desc)
                found[ch] = {"username": ch, "title": title, "desc": desc, "score": score}
        time.sleep(2)
    return found

def discover_discord():
    found = {}
    for tag in DISCORD_TAGS:
        print(f"discord tag: {tag}")
        text = jina_get(f"https://disboard.org/search?keyword={tag}")
        for m in re.finditer(r"discord\.gg/([a-zA-Z0-9]+)", text):
            inv = m.group(1)
            found[inv] = {"invite": inv, "source": "disboard", "tag": tag}
        time.sleep(2)
    return found

def learn_codewords(items):
    suspicious = [
        ("读书会", "招募"), ("分享会", "志愿者"), ("野餐", "集会"),
        ("调研", "走访"), ("公益", "募捐"), ("沙龙", "论坛"),
    ]
    learned = []
    for a, b in suspicious:
        count = sum(1 for it in items if a in (it.get("title","")+it.get("summary",""))
                    and b in (it.get("title","")+it.get("summary","")))
        if count > 0:
            learned.append({"pair": [a, b], "count": count})
    return learned

def main():
    print("=== TG discover ===")
    tg = discover_tg()
    print(f"found {len(tg)} channels")

    print("\n=== Discord discover ===")
    dc = discover_discord()
    print(f"found {len(dc)} discord invites")

    cfg = json.load(open(CFG))
    existing = {c["name"] for c in cfg.get("business_channels", [])}

    new_auto = []
    for ch, info in tg.items():
        if ch not in existing and info["score"] >= 20:
            cfg["business_channels"].append({"name": ch, "alias": info["title"][:30]})
            new_auto.append(ch)

    if new_auto:
        json.dump(cfg, open(CFG, "w"), ensure_ascii=False, indent=2)
        print(f"\nauto-added to watch: {new_auto}")

    learned = learn_codewords(list(tg.values()))

    out = {
        "tg_found": tg, "discord_found": dc,
        "auto_added": new_auto, "codewords_learned": learned,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\nsaved: {OUT}")

if __name__ == "__main__":
    main()
