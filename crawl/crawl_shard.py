# -*- coding: utf-8 -*-
"""采集分片工人 v2：在 GitHub Actions（有外网）上跑。
  1) 拉源清单 → RSS/首页取条目
  2) 顺手抓正文（纯代码启发式，不用模型）→ 正文≥400 字的才算合格
  3) 每片最多抓 BODY_MAX 篇正文，避免单 job 超时
输出：out/crawl_<shard>.json
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.parse
import email.utils as eut
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; intelhub-swarm/1.0)"}
BODY_MIN = 260
BODY_MAX = 96
HOURS = 24


def _ts(s):
    """把 RSS/网页里的发布时间解析成时间戳，解析不出来返回 0（当新料处理）"""
    if not s:
        return 0
    s = s.strip()[:32]
    try:
        return eut.parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d",
                "%Y年%m月%d日", "%d %b %Y", "%a, %d %b %Y %H:%M:%S"):
        try:
            import datetime as _d
            return _d.datetime.strptime(s[:len(fmt) * 2], fmt).timestamp()
        except Exception:
            continue
    import re as _re
    m = _re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        import datetime as _d
        try:
            return _d.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).timestamp()
        except Exception:
            return 0
    return 0


def parse_feed(text):
    out = []
    try:
        root = ET.fromstring(text)
    except Exception:
        return out
    for it in root.iter():
        if it.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        title = link = date = desc = ""
        for ch in it:
            t = ch.tag.split("}")[-1].lower()
            if t == "title":
                title = (ch.text or "").strip()
            elif t == "link":
                link = (ch.text or ch.attrib.get("href") or "").strip()
            elif t in ("pubdate", "published", "updated", "date"):
                date = (ch.text or "").strip()[:32]
            elif t in ("description", "summary", "content"):
                desc = re.sub(r"<[^>]+>", "", (ch.text or ""))[:600]
        if title and link.startswith("http"):
            out.append({"title": title, "url": link, "published": date, "summary": desc})
    return out


def parse_html(base, text):
    out = []
    host = urllib.parse.urlparse(base).netloc
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
        href, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not (12 <= len(label) <= 90):
            continue
        u = urllib.parse.urljoin(base, href)
        if urllib.parse.urlparse(u).netloc != host:
            continue
        if re.search(r"[#?]|/tag/|/category/|/page/|/author/", u):
            continue
        out.append({"title": label, "url": u, "published": "", "summary": ""})
    return out[:50]


_DROP = re.compile(r"<(script|style|nav|header|footer|aside|form|iframe)[^>]*>.*?</\1>", re.S | re.I)
_NOISE = re.compile(r"(责任编辑|版权所有|Copyright|cookie|Cookie|隐私政策|免费登录|账号登录|注册账号|免费注册|注册登录|扫一扫|扫码|下载APP|关注我们|点击订阅)")


_NAV_LINE = re.compile(r"(访问主要内容|管理我的许可证|回到首页|网站导航|隐私政策|Cookie|点击订阅|账号登录|注册账号|免费注册|分享到|相关新闻|同一主题|其他新闻|推荐阅读|点击查看|广告|Advertisement|Privacy|Terms of use|Copyright|版权所有|关于我们|联系我们)")
_COLWORD = re.compile(r"(时事|科技|文化|管理|国际|中国|亚洲|欧洲|美洲|非洲|观点|视频|图集|专题|专栏)")


def scrub_body(body):
    """采集端正文清洗：按句切分，逐句丢导航/栏目/残片，压缩空白（与 qc_body.scrub_page 同口径）"""
    raw = re.split(r"(?<=[。！？；])", str(body or ""))
    out = []
    for line in raw:
        x = line.strip()
        if not x:
            continue
        if x.startswith("[Image") or x.startswith("[](") or x.startswith("[访问"):
            continue
        if _NAV_LINE.search(x):
            continue
        if len(x) <= 12 and _COLWORD.search(x):
            continue
        if len(x) <= 4 and not re.search(r"[，。！？；：、]", x):
            continue
        out.append(x)
    t = " ".join(out)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"([，。！？；：])\1+", r"\1", t)
    return t.strip()


def extract_body(html_text):
    """纯代码抽正文：去脚本，取连续 <p>，兜底整页文本，最后统一 scrub_body 清渣"""
    t = _DROP.sub(" ", html_text)
    ps = re.findall(r"<p[^>]*>(.*?)</p>", t, re.S | re.I)
    cand = []
    for p in ps:
        s = re.sub(r"<[^>]+>", "", p)
        s = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 25 and not _NOISE.search(s):
            cand.append(s)
    body = scrub_body("".join(cand))
    if len(body) < BODY_MIN:  # p 不够，整页文本先 scrub 再比较，防止导航块并句污染
        s = re.sub(r"<[^>]+>", " ", t)
        s = re.sub(r"\s+", " ", s).strip()
        s = scrub_body(s)
        body = s if len(s) > len(body) else body
    return body


_ORG_SUFFIX = "部|局|委员会|办公室|司令部|研究所|研究院|实验室|基金会|公司|集团|银行|中心|大学|学院|协会|联盟|议会|法院|使馆|总部|委|署|院"
_ORG_RE = re.compile(u"([\u4e00-\u9fa5]{2,10}(?:%s))" % _ORG_SUFFIX)
# 机构名前缀里的动词/连接词噪声（“据悉美财政部”→ 去掉“据悉”）
_LEAD = re.compile(u"^(?:据[^\\s,，。]{0,4}?称?|据悉|报道称|报道|消息称|分析称|评论称|宣称|声称|表示|宣布|指出|认为|显示|称|说|另据|此外|同时|目前|近日|日前|昨天|昨日|今天|当日|其中|以及|并且|但是|然而|因为|所以|如果|已经|正式|首次|再次|拟|将|被|由|向|对|从|在|与|和|及|该|其|此|这|本|我国|该国)")
_AMT_RE = re.compile(u"(\\d+(?:\\.\\d+)?\\s*(?:亿|万|千)?\\s*(?:美元|欧元|日元|英镑|卢布|人民币|元|吨|架|艘|枚|桶|加仑|人|名|%|％))")
_CODE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,6}(?:-\d{2,6})+")
_GENERIC = re.compile(u"^(有关|相关|其他|其余|各|某|部分|多个|一些|上述|以上|当地|这家|那家|任何|全部|所有|多家|数家)")
  # 前缀噪声：逐个剥掉开头的动词/连接词，直到剥不动
_LEADCH = u"据称悉讯闻表宣指认显说评此该其也将被由向对从在与和及的了是乃即另仍再已正共各"
def _clean_org(s):
    while s and s[0] in _LEADCH:
        s = s[1:]
    return s


def extract_facts(text):
    """纯代码抽硬事实：机构主体 / 金额数量 / 代号型号。宁可少，不许编。"""
    t = text or ""
    orgs, amts, codes = [], [], []
    for m in _ORG_RE.finditer(t):
        s = _clean_org(_LEAD.sub("", m.group(1)))
        s = s.lstrip(u"的了是在和与及对向从被由该其此这那")
        if 3 <= len(s) <= 14 and not _GENERIC.search(s[:4]):
            orgs.append(s)
    for m in _AMT_RE.finditer(t):
        v = m.group(1).replace(" ", "")
        if re.search(u"\\d", v):
            amts.append(v)
    for m in _CODE_RE.finditer(t):
        codes.append(m.group(0))
    return {
        "orgs": list(dict.fromkeys(orgs))[:3],
        "amts": list(dict.fromkeys(amts))[:3],
        "codes": list(dict.fromkeys(codes))[:3],
    }


def title_in_body(title, body):
    """标题相关性硬校验：标题的汉字二元组至少 2 个出现在正文里，防串台/防样板页冒充"""
    zh = re.findall(u"[\u4e00-\u9fa5]{2,}", title or "")
    grams = set()
    for seg in zh:
        for i in range(len(seg) - 1):
            grams.add(seg[i:i + 2])
    if len(grams) < 3:
        return True  # 短标题不判
    hit = sum(1 for g in grams if g in body)
    return hit >= 2


def zh_ratio(t):
    t2 = re.sub(r"\s", "", t or "")
    return len(re.findall(u"[\u4e00-\u9fa5]", t2)) / float(max(1, len(t2)))


def translate_zh(text, cap=4200):
    """英文原文机翻成中文（纯接口，不用模型）。分批 600 字，失败保留原文。"""
    text = (text or "")[:cap]
    if not text.strip():
        return ""
    out = []
    for i in range(0, len(text), 600):
        chunk = text[i:i + 600]
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": chunk},
                headers=UA, timeout=15)
            data = r.json()
            out.append("".join(x[0] for x in data[0] if x and x[0]))
        except Exception as e:
            print("TR-SKIP %s" % str(e)[:40])
            return ""
    return "".join(out)


def get(url, timeout=20, jina=False):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code < 400:
            return r.text
        code = r.status_code
    except Exception:
        code = 0
    if jina:
        ju = "https://r.jina.ai/" + url
        r2 = requests.get(ju, headers=UA, timeout=timeout + 10)
        if r2.status_code < 400:
            return r2.text
    raise RuntimeError("HTTP %s" % code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--total", type=int, default=8)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--body-max", type=int, default=BODY_MAX)
    ap.add_argument("--hours", type=int, default=HOURS, help="只收这么多小时内发布的（0=不限）")
    ap.add_argument("--sources", default="")
    ap.add_argument("--sources-url", default="")
    ap.add_argument("--out", default="out/crawl.json")
    a = ap.parse_args()

    srcs = json.loads(get(a.sources_url)) if a.sources_url else json.load(open(a.sources, encoding="utf-8"))
    mine = [s for i, s in enumerate(srcs) if i % a.total == a.shard][:a.n]

    rows = []
    stats = {"src_tried": 0, "src_ok": 0, "items": 0, "body_tried": 0, "body_ok": 0}
    per_host = {}

    def _ph(host, key, n=1):
        h = (host or "?")[:80]
        d = per_host.setdefault(h, {"src_tried": 0, "src_ok": 0, "body_ok": 0,
                                    "drop_short": 0, "drop_nofact": 0, "drop_offtopic": 0, "fail": 0})
        d[key] = d.get(key, 0) + n
    for s in mine:
        payload = (s.get("feed_url") or s.get("base") or s.get("ref") or "").strip()
        if not payload.startswith("http"):
            continue
        stats["src_tried"] += 1
        _ph(s.get("host"), "src_tried")
        try:
            txt = get(payload, jina=(str(s.get("status") or "") == "need_jina"))
            items = parse_feed(txt) or parse_html(payload, txt)
            if not items:
                continue
            stats["src_ok"] += 1
            _ph(s.get("host"), "src_ok")
            for it in items[:60]:
                it["source"] = (s.get("name") or s.get("host") or "")[:60]
                it["host"] = (s.get("host") or "")[:80]
                rows.append(it)
        except Exception as e:
            print("SKIP %s %s" % (payload[:60], str(e)[:50]))

    # 新鲜度过滤：只要最近 hours 小时内的；解析不出时间的保留（当作新料）
    if a.hours:
        cutoff = time.time() - a.hours * 3600
        rows = [r for r in rows if _ts(r.get("published")) == 0 or _ts(r.get("published")) >= cutoff]
    stats["fresh"] = len(rows)
    # 新的排前面，先给最新的抓正文
    rows.sort(key=lambda r: -_ts(r.get("published")))
    picked = rows[:a.body_max]
    for it in picked:
        stats["body_tried"] += 1
        try:
            body = ""
            for _uj in (False, True):
                try:
                    body = extract_body(get(it["url"], timeout=15, jina=_uj))
                except Exception:
                    body = ""
                if len(re.findall(r"[\u4e00-\u9fa5]", body)) >= 180:
                    break
            han = len(re.findall(r"[\u4e00-\u9fa5]", body))
            hit = title_in_body(it.get("title") or "", body)
            if han >= BODY_MIN and hit:
                it["body"] = body[:8000]
                it["body_len"] = han
                stats["body_ok"] += 1
                _ph(it.get("host"), "body_ok")
            else:
                it["body"] = ""
                it["body_len"] = 0
                it["title_only"] = 1
        except Exception as e:
            it["body"] = ""
            it["body_len"] = 0
            it["title_only"] = 1
            _ph(it.get("host"), "fail")
            print("BODY-SKIP %s %s" % (it["url"][:60], str(e)[:40]))
        # 英文/外文原文：就地机翻成中文，翻不出来就不回传（中文研判写不出英文料的深度）
        if (it.get("body_len") or 0) >= BODY_MIN and zh_ratio(it.get("body") or "") < 0.5:
            tr = translate_zh(it.get("body") or "")
            if tr and zh_ratio(tr) >= 0.5:
                it["body_orig"] = it["body"][:1200]
                it["body"] = tr
                it["body_len"] = len(tr)
                it["translated"] = 1
            else:
                it["body"] = ""
                it["body_len"] = 0
                it["title_only"] = 1
        time.sleep(0.3)

    # 有正文的排前面，方便服务器先吃好的
    picked.sort(key=lambda x: -int(x.get("body_len") or 0))
    keep = []
    for x in picked:
        if (x.get("body_len") or 0) < BODY_MIN:
            stats["drop_short"] = stats.get("drop_short", 0) + 1
            _ph(x.get("host"), "drop_short")
            continue
        # ① 串台/样板门：标题必须真的在正文里出现
        if not title_in_body(x.get("title", ""), x.get("body", "")):
            stats["drop_offtopic"] = stats.get("drop_offtopic", 0) + 1
            _ph(x.get("host"), "drop_offtopic")
            continue
        # ② 硬事实：机构 / 金额 / 代号 至少一项
        f = extract_facts(x.get("body", ""))
        x["facts"] = f
        x["fact_n"] = len(f["orgs"]) + len(f["amts"]) + len(f["codes"])
        if x["fact_n"] == 0:
            stats["drop_nofact"] = stats.get("drop_nofact", 0) + 1
            _ph(x.get("host"), "drop_nofact")
            continue
        keep.append(x)
    # 事实多的排前面：服务器按顺序吃，先消化证据最足的
    keep.sort(key=lambda x: (-x.get("fact_n", 0), -int(x.get("body_len") or 0)))
    stats["items"] = len(keep)
    stats["fact_ok"] = sum(1 for x in keep if x.get("fact_n", 0) >= 2)
    out = {"shard": a.shard, "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "stats": stats, "per_host": per_host, "rows": keep}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
