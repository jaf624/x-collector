# -*- coding: utf-8 -*-
"""在 commit 前把 origin/main 的 data 与工作区 data 按主键合并，避免 rebase 冲突丢数据。
由 commit_feed.sh 调用（已 git fetch origin）。"""
import subprocess, json, os
MERGE = {
    "data/intel_brief.json": "url",
    "data/intel_feed.json": "url",
    "data/telegram_feed.json": "url",
    "data/x_feed.json": "x_id",
    "data/gh_feed.json": "gh_id",
}

def git_show(path):
    r = subprocess.run(["git", "show", "origin/main:" + path], capture_output=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8", "ignore"))
    except Exception:
        return None

def _nonempty(v):
    return v not in (None, "", [], {})

def merge_list(base, head, key):
    """base=origin 版本, head=工作区版本。同 key 工作区字段覆盖、保留更长正文。"""
    by, order = {}, []
    for x in base:
        k = x.get(key)
        if k and k not in by:
            by[k] = x; order.append(k)
    for x in head:
        k = x.get(key)
        if not k:
            continue
        if k in by:
            m = dict(by[k])
            for f, v in x.items():
                if _nonempty(v):
                    m[f] = v
            if len(x.get("content", "") or "") > len(by[k].get("content", "") or ""):
                m["content"] = x["content"]
            by[k] = m
        else:
            by[k] = x; order.append(k)
    return [by[k] for k in order]

for path, key in MERGE.items():
    if not os.path.exists(path):
        continue
    origin = git_show(path)
    try:
        head = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if origin is None:
        print("no origin", path); continue
    if isinstance(origin, list) and isinstance(head, list):
        merged = merge_list(origin, head, key)
        json.dump(merged, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print("merged %s: origin %d + head %d -> %d" % (path, len(origin), len(head), len(merged)))
