#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 定向优质源采集器（海外 runner 运行，零登录）。
不做泛搜（会捞到垃圾项目），只抓公认高质量的中文提示词合集仓库，
按 "## 标题 + > 引用正文" 的标准结构解析成干净提示词条目，累积去重写 data/gh_feed.json。
"""
import os, re, json, time, datetime, pathlib, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
OUT_DIR = ROOT / "data"; OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "gh_feed.json"
UA = "Mozilla/5.0 (compatible; prompt-hub-bot)"

# 优质中文提示词源（owner/repo: 分支/README路径）
SOURCES = [
    ("PlexPt/awesome-chatgpt-prompts-zh", "main", "README.md", "GitHub:经典中文调教"),
]

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def is_cjk(s):
    return sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff')

def parse_role_prompts(md, source_tag):
    """解析 '## 角色名' + '> 正文' 结构。"""
    entries = []
    lines = md.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = re.match(r'^##\s+(.+?)\s*$', line)
        if not m:
            i += 1; continue
        title = m.group(1).strip()
        # 跳过介绍性/非提示词标题
        skip_kw = ["它能干", "微信", "交流群", "项目合作", "国内中文", "目录", "贡献", "License", "许可证"]
        if any(k in title for k in skip_kw) or is_cjk(title) < 2:
            i += 1; continue
        # 收集标题后面连续的 > 引用行 或 ``` 代码块
        body = []
        j = i + 1
        in_code = False
        while j < n:
            l = lines[j].rstrip()
            if l.startswith("## "): break          # 下一个条目
            if l.strip().startswith("```"):
                in_code = not in_code; j += 1; continue
            if in_code:
                body.append(l)
            elif l.lstrip().startswith(">"):
                body.append(re.sub(r'^\s*>\s?', '', l))
            elif l.strip() == "" and body:
                # 空行后若没有更多 > 则结束该条目
                k = j + 1
                if k < n and not lines[k].lstrip().startswith(">") and not lines[k].strip().startswith("```"):
                    break
            j += 1
        text = "\n".join(b for b in body if b.strip()).strip()
        if len(text) < 25 or is_cjk(text) < 15:
            i = j; continue
        entries.append({
            "title": title[:24],
            "content": text[:1200],
            "source": source_tag,
            "source_url": "",
        })
        i = j
    return entries

def main():
    recs = []
    for owner_repo, branch, readme, tag in SOURCES:
        url = f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{readme}"
        try:
            md = http_get(url)
        except Exception as e:
            print("[src]", owner_repo, "fail", str(e)[:80]); continue
        ents = parse_role_prompts(md, tag)
        print(f"[src] {owner_repo}: 解析出 {len(ents)} 条")
        for e in ents:
            e["gh_id"] = f"{owner_repo}::{e['title']}"
            e["source_url"] = f"https://github.com/{owner_repo}"
            e["lang"] = "zh"
            e["fetched_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            recs.append(e)
        time.sleep(1)

    old = {}
    if OUT.exists():
        try: old = {x["gh_id"]: x for x in json.loads(OUT.read_text("utf-8"))}
        except Exception: old = {}
    for r in recs:
        if r.get("gh_id"): old[r["gh_id"]] = r
    feed = sorted(old.values(), key=lambda x: x.get("fetched_at", ""), reverse=True)
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=2), "utf-8")
    print(f"完成：本次 {len(recs)} 条，累积 {len(feed)} 条 -> {OUT}")

if __name__ == "__main__":
    main()
