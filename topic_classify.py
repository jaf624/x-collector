# -*- coding: utf-8 -*-
"""题材分类器（纯代码、零模型）：直接用系统内的 classify_config_v2.json。

为什么要用配置而不是自己写词表：
  1. 系统里 18 个题材已经定义过优先级（primary_order）、权重（weight 1-5）和四层词表
     （core / ext / core_extra / ext_extra），出稿、打分、配额都在用同一套口径；
  2. 采集端若另写一套词表，就会和出稿端"对不上"——采集认为相关的，出稿端认不出来；
  3. 用同一份配置，采集端等于提前按"最终选题标准"筛料。

匹配规则（照 match_rule 原文）：
  core/ext 为正式清单原词；core_extra/ext_extra 是通用补充兜底层；
  核心层命中即匹配；仅拓展层命中需 ≥2 次；
  多分类按命中分（核心 2 / 拓展 1）排序，再按 primary_order 决胜。

对外：
  best(text)      -> (cat_id, name, weight, score) 或 None
  classify(text)  -> [(cat, name, weight, score), ...]（按分数降序）
"""
import json, os, re

_CFG = None
_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify_config_v2.json")


def load(path=None):
    global _CFG
    if _CFG is not None:
        return _CFG
    p = path or os.environ.get("INTEL_CLASSIFY_CFG") or _DEFAULT
    cfg = json.load(open(p, encoding="utf-8"))
    cats = []
    for cid, v in cfg["categories"].items():
        layers = []
        for f, w in (("core", 2), ("ext", 1), ("core_extra", 2), ("ext_extra", 1)):
            for kw in v.get(f, []) or []:
                kw = str(kw).strip()
                if kw:
                    layers.append((re.compile(re.escape(kw), re.I), w))
        cats.append({"id": cid, "name": v.get("name", cid), "weight": v.get("weight", 3),
                     "rules": layers, "formal_ext": bool(v.get("ext"))})
    order = {c: i for i, c in enumerate(cfg.get("primary_order", []))}
    _CFG = {"cats": cats, "order": order, "china_kw": cfg.get("china_keywords", []),
            "default": cfg.get("default_cat", "c6")}
    return _CFG


def classify(text, cap=1500):
    cfg = load()
    t = (text or "")[:cap]
    out = []
    for c in cfg["cats"]:
        score = 0
        core_hit = False
        for rx, w in c["rules"]:
            if rx.search(t):
                score += w
                if w >= 2:
                    core_hit = True
        if core_hit or score >= 2:          # 核心层直接成立；仅拓展层要累计 ≥2
            out.append((c["id"], c["name"], c["weight"], score))
    out.sort(key=lambda x: (-x[3], cfg["order"].get(x[0], 99)))
    return out[:4]


def best(text, cap=1500):
    r = classify(text, cap)
    return r[0] if r else None


def is_china(text, cap=1500):
    cfg = load()
    t = (text or "")[:cap].lower()
    return any(str(k).lower() in t for k in cfg["china_kw"])


def cats(*a, **k):
    return [c["id"] for c in load()["cats"]]


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        print(s[:30], "->", best(s), "china=", is_china(s))
