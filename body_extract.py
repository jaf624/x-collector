#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""body_extract.py — 通用网页正文抽取（纯代码，无模型、无第三方库）

设计依据（记忆引擎）：
- content>200 ≠ 有事实：长度会骗人，必须有「长段落 + 标题相关性 + 噪声词」三重校验；
- 站点样板说明（如联邦公报 "does not replace the official print version"）会被当正文，
  导致事实句数虚高，必须整段剔除；
- 单套逻辑两处复用（采集端深抓、服务器端补抓），避免规则分叉。

对外接口：
    txt, why = extract(html, title="")     # 返回 (正文, 判定说明)
"""
import re

NOISE_SUB = (
    "立即注册", "了解亚洲", "发布于20", "订阅我们", "Subscribe", "Sign in", "Log in",
    "prototype of a", "does not replace the official", "official print version",
    "This site displays", "official legal edition", "govinfo", "legal research should verify",
    "Enable JavaScript", "You are using an unsupported browser", "Cookie", "隐私政策",
    "版权所有", "责任编辑", "扫码关注", "下载APP", "相关阅读", "热门推荐", "分享到",
    "Advertisement", "Sponsored", "All rights reserved",
)
NAV_LINE = re.compile(
    r"^(首页|新闻|财经|科技|体育|娱乐|视频|图片|专题|直播|关于我们|联系我们|网站地图|"
    r"Home|News|World|Business|Opinion|Sports|Subscribe|Menu|Search)\b")
STOP_TITLE = ("我国", "影响", "分析", "相关", "动向", "警惕")


def _strip_tags(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|iframe|form)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?is)<!--.*?-->", " ", h)
    return h


def _clean(t):
    t = re.sub(r"\{\{[^}]*\}\}", " ", t)
    t = re.sub(r"&nbsp;|&amp;|&quot;|&lt;|&gt;|&#\d+;", " ", t)
    t = re.sub(r"\[?[（(]?Images?\s*\d+[)）]?", " ", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    out = []
    for ln in re.split(r"[\r\n]+", t):
        ln = ln.strip()
        if len(ln) < 12:
            continue
        if NAV_LINE.match(ln):
            continue
        if any(n in ln for n in NOISE_SUB):
            continue
        out.append(ln)
    return "。".join(out) if len(out) > 1 else (out[0] if out else "")


def title_kws(title):
    kws = [w for w in re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z]{4,}", title or "")]
    return [w for w in kws if w not in STOP_TITLE][:8]


def title_related(title, txt):
    kws = title_kws(title)
    if not kws:
        return True
    return sum(1 for w in kws if w in txt) >= min(2, len(kws))


def facts_count(txt):
    n = 0
    for s in re.split(r"[。！？\n]", txt or ""):
        if len(s) < 14:
            continue
        if re.search(r"\d", s) or re.search(
                r"公司|机构|组织|政府|部门|军方|委员会|法院|银行|大学|协会|公司|集团", s):
            n += 1
    return n


def extract(html, title=""):
    """返回 (正文, 判定说明)。正文不合格时返回 ("", 原因)。"""
    if not html or len(html) < 200:
        return "", "empty_html"
    h = _strip_tags(html)

    blocks = []
    for tag in ("article", "main", "div"):
        for m in re.finditer(r"(?is)<%s[^>]*>(.*?)</%s>" % (tag, tag), h):
            blocks.append(m.group(1))
            if tag != "div" and len(blocks) >= 6:
                break
    blocks.append(h)

    best = ""
    for b in blocks:
        ps = re.findall(r"(?is)<p[^>]*>(.*?)</p>", b)
        if not ps:
            ps = re.split(r"(?is)<br\s*/?>|</(?:div|h\d|li)>", b)[:400]
            ps = [p for p in ps if len(re.sub(r"<[^>]+>", "", p).strip()) >= 40]
        ps = [_clean(re.sub(r"(?is)<[^>]+>", "", p)) for p in ps]
        ps = [q for q in ps if len(q) >= 30]
        if not ps:
            continue
        longest = max(ps, key=len)
        if len(longest) < 120:
            continue
        i = ps.index(longest)
        txt = "。".join(ps[max(0, i - 3): i + 4])
        if len(txt) >= 300 and len(txt) > len(best):
            best = txt

    if len(best) < 200:
        return "", "no_long_paragraph"
    if title and not title_related(title, best):
        return "", "offtopic"
    if facts_count(best) < 2:
        return "", "no_fact"
    return best[:3000], "ok"


# ---------- 评论抽取（静态 HTML 前 N 条跟帖；动态 JS/登录墙取不到返回 []） ----------
_CMT_AUTHOR = re.compile(r'(?i)class="[^"]*(?:author|username|user-name|name)[^"]*"[^>]*>([^<>]{2,40})<')
_CMT_LIKES = re.compile(r'(?i)(?:score|likes?|upvotes?|votes?|replies?)\D{0,6}(\d{1,4})')
_CMT_TIME = re.compile(r'datetime="([^"]+)"|((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s*\d{1,2}(?:,\s*\d{4})?)')


def _comment_clean(t):
    t = re.sub(r"&nbsp;|&amp;|&quot;|&lt;|&gt;|&#\d+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_comments(html, max_n=2):
    """返回 [{author, text, likes, time}]，最多 max_n 条；取不到返回 []。

    只解析服务端直出的静态评论块（论坛/Reddit/留言板/部分 Disqus）；
    由 JS 异步加载、登录墙、弹窗内的评论不在 HTML 里，自然抽不到，留空即可。
    """
    if not html or len(html) < 200:
        return []
    h = _strip_tags(html)
    blocks = []
    for tag in ("li", "div", "article"):
        pat = r'(?is)<%s[^>]*(?:class|id)="[^"]*(?:comment|reply|review|response)[^"]*"[^>]*>(.*?)</%s>' % (tag, tag)
        blocks += re.findall(pat, h)
    out, seen = [], set()
    for b in blocks:
        b2 = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", b)
        au = _CMT_AUTHOR.search(b2)
        author = au.group(1).strip() if au else ""
        lk = _CMT_LIKES.search(b2)
        likes = int(lk.group(1)) if lk else None
        tm = _CMT_TIME.search(b2)
        ctime = ""
        if tm:
            ctime = next((g for g in (tm.group(1), tm.group(2)) if g), "")
        ps = re.findall(r"(?is)<p[^>]*>(.*?)</p>", b2)
        ps = [_comment_clean(re.sub(r"(?is)<[^>]+>", " ", p)) for p in ps]
        ps = [p for p in ps if len(p) >= 15]
        text = max(ps, key=len) if ps else _comment_clean(re.sub(r"(?is)<[^>]+>", " ", b2))
        if len(text) < 15 or len(text) > 600:
            continue
        if author and text.startswith(author):
            text = text[len(author):].strip()
        key = text[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append({"author": author, "text": text[:300], "likes": likes, "time": ctime})
        if len(out) >= max_n:
            break
    return out
