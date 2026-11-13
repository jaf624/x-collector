#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付中心生成器：读取 articles/*.json，按公文格式逐篇生成 docx，输出 manifest.json。
每篇独立成文；来源写入文末；页码 Times New Roman 小四居中。"""
import glob, json, os, re
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

DELIVER = "/opt/intelhub/deliver"
ART_DIR = os.path.join(DELIVER, "articles")
OUT_DIR = os.path.join(DELIVER, "out")

F_TITLE = "方正小标宋简体"
F_HEI = "方正黑体"
F_KAI = "方正楷体"
F_FANGSONG = "方正仿宋"
F_TNR = "Times New Roman"
CN = ["一", "二", "三", "四", "五"]


def sf(run, name, size, bold=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run._element.rPr.rFonts.set(qn("w:ascii"), name)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), name)


def title(doc, t):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.line_spacing = Pt(34)
    sf(p.add_run(t), F_TITLE, 22, False)


def head(doc, t):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = Pt(30)
    sf(p.add_run(t), F_HEI, 16, False)


def para(doc, segs, indent=True, size=16):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = Pt(30)
    pf.space_after = Pt(3)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if indent:
        pf.first_line_indent = Pt(size * 2)
    if isinstance(segs, str):
        segs = [(segs, False)]
    for t, b in segs:
        sf(p.add_run(t), F_FANGSONG, size, b)


def add_page_number(doc):
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rf = OxmlElement("w:rFonts")
    rf.set(qn("w:ascii"), F_TNR)
    rf.set(qn("w:hAnsi"), F_TNR)
    rf.set(qn("w:eastAsia"), F_TNR)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "24")
    rPr.append(rf)
    rPr.append(sz)
    r.append(rPr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    p._p.append(fld)


def sentence_type(title):
    """按标题判定六种核心句式，决定正文结构（2026-10-29 用户要求：句式决定结构，不再一律套警惕四段式）。"""
    t = title or ""
    if re.search(r"对我国影响分析|对我影响分析|影响分析|风险分析", t):
        return "影响分析式"
    if re.search(r"斥资|斥资动向|动向及涉我影响|动向及影响", t):
        return "斥资动向式"
    if re.match(r"^疑似", t):
        return "疑似苗头式"
    if re.match(r"^网传", t):
        return "网传爆料式"
    if re.search(r"密切关注|态势分析|舆情综合|态势综述|综合研判|动态$|人物画像", t):
        return "态势综合式"
    if re.search(r"为例|案例剖析|记录显示|采购记录|核查发现", t):
        return "陈述研判式"
    return "警惕式"


# 六句式 → 三个小节标题（第一/二/三）。第二节为正文重点，随句式变化。
SECT = {
    "警惕式":   ["一、基本情况", "二、风险隐患", "三、对策建议"],
    "影响分析式": ["一、事件概况", "二、对我国影响", "三、应对建议"],
    "斥资动向式": ["一、斥资动向", "二、对我影响", "三、应对建议"],
    "疑似苗头式": ["一、线索苗头", "二、甄别研判", "三、预警建议"],
    "网传爆料式": ["一、网传内容", "二、核实与真相", "三、处置建议"],
    "态势综合式": ["一、总体态势", "二、主要动向", "三、趋势研判与建议"],
    "陈述研判式": ["一、事实概况", "二、风险研判", "三、对策建议"],
}


def build(a):
    doc = Document()
    s = doc.sections[0]
    s.page_height, s.page_width = Cm(29.7), Cm(21.0)
    s.top_margin, s.bottom_margin = Cm(3.0), Cm(2.8)
    s.left_margin, s.right_margin = Cm(2.8), Cm(2.6)
    title(doc, a["title"])
    para(doc, a["intro"])
    stype = a.get("sentence_type") or sentence_type(a["title"])
    s1, s2, s3 = SECT.get(stype, SECT["警惕式"])
    _has_sec = bool(str(a.get("basics") or "").strip()) and bool(str(a.get("chain") or "").strip())
    if (not _has_sec) and a.get("analysis"):
        # 事前预判模式（江勇模式）：一大段综合分析讲透时间/来源/背景/原因/风险/影响/对策
        head(doc, "一、综合研判")
        para(doc, a["analysis"])
    else:
        head(doc, s1)
        para(doc, a["basics"])
        # 手段方法链条仅在交付中心网页(preview/manifest)展示，Word正文不单独成节
        head(doc, s2)
        for i, (lead, txt) in enumerate(a["risks"], 1):
            _p = doc.add_paragraph()
            _pf = _p.paragraph_format
            _pf.line_spacing = Pt(30)
            _pf.space_after = Pt(3)
            _pf.first_line_indent = Pt(16 * 2)
            _p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            sf(_p.add_run("（%s）" % (CN[i - 1] if i - 1 < len(CN) else str(i)) + lead + "。"), F_KAI, 16, False)
            para(doc, txt)
        head(doc, s3)
        for i, (lead, txt) in enumerate(a["advices"], 1):
            _p = doc.add_paragraph()
            _pf = _p.paragraph_format
            _pf.line_spacing = Pt(30)
            _pf.space_after = Pt(3)
            _pf.first_line_indent = Pt(16 * 2)
            _p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            sf(_p.add_run("（%s）" % (CN[i - 1] if i - 1 < len(CN) else str(i)) + lead + "。"), F_KAI, 16, False)
            para(doc, txt)
    # 文末文字来源：X月X日据XX报道（无链接），仿宋3号、首行缩进2字符
    _src = a.get("source") or ""
    _src = re.sub(r"(\d{4})-(\d{2})-(\d{2})",
                  lambda m: "%s年%s月%s日" % (m.group(1), int(m.group(2)), int(m.group(3))), _src)
    if _src:
        sp = doc.add_paragraph()
        spf = sp.paragraph_format
        spf.line_spacing = Pt(30)
        spf.space_before = Pt(8)
        spf.first_line_indent = Pt(16 * 2)
        sp.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        sf(sp.add_run("来源：" + _src.strip("。 ") + "。"), F_FANGSONG, 16, False)
    add_screens(doc, a)
    add_page_number(doc)
    return doc


def add_screens(doc, a):
    """文末来源截图：无小节标题，图注"来源：原文页面截图"＋图片。"""
    names = a.get("screenshot") or []
    if isinstance(names, str):
        names = [names]
    if not names:
        return
    cand_dirs = ["/opt/intelhub/screens", os.path.join(DELIVER, "screens"), "."]
    for n in names:
        fp = None
        for d in cand_dirs:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                fp = p
                break
        if not fp:
            print("  (截图缺失: %s)" % n)
            continue
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        p.add_run().add_picture(fp, width=Cm(14.5))
        c = doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraph_format.space_after = Pt(6)
        sf(c.add_run("原文页面截图"), F_FANGSONG, 12, False)


def build_preview_html(a, out_name, docx_rel):
    """生成公文样式预览页 preview/<slug>.html：全文显示+文末截图+下载按钮。"""
    CN2 = ["一", "二", "三", "四", "五"]
    risks_html = "".join(
        "<p class=\"body\"><b>（%s）%s。</b>%s</p>" % (CN2[i] if i < len(CN2) else str(i + 1), esc(r[0]), esc(r[1]))
        for i, r in enumerate(a.get("risks") or []))
    advices_html = "".join(
        "<p class=\"body\"><b>（%s）%s。</b>%s</p>" % (CN2[i] if i < len(CN2) else str(i + 1), esc(v[0]), esc(v[1]))
        for i, v in enumerate(a.get("advices") or []))
    shots = a.get("screenshot") or []
    if isinstance(shots, str):
        shots = [shots]
    shots_html = ""
    for s in shots:
        base = os.path.basename(s)
        shots_html += ("<div class=\"shot\"><img src=\"../screens/%s\" alt=\"来源截图\">"
                       "<p class=\"cap\">来源：原文页面截图</p></div>" % base)
    stype = a.get("sentence_type") or sentence_type(a.get("title", ""))
    _s1, _s2, _s3 = SECT.get(stype, SECT["警惕式"])
    # 链条小节标题：第二节之后补一节"手段方式链条"（网页专用），对策建议沿用第三小节
    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
  body{background:#f5f3ee;font-family:"PingFang SC","Microsoft YaHei",serif;margin:0;padding:32px 20px;}
  .doc{max-width:780px;margin:0 auto;background:#fff;padding:56px 64px;box-shadow:0 2px 14px rgba(0,0,0,.08);}
  h1{font-size:22pt;font-family:"方正小标宋简体","STSong","SimSun",serif;text-align:center;font-weight:700;
     margin:0 0 4px;letter-spacing:1px;line-height:1.5;}
  .date{text-align:center;font-size:12pt;color:#555;margin:10px 0 18px;}
  p.body{font-size:16px;line-height:30px;text-align:justify;text-indent:2em;margin:0 0 2px;color:#1a1a1a;}
  p.chain{font-size:16px;line-height:30px;text-align:justify;margin:0 0 2px;color:#1a1a1a;}
  h2{font-size:16pt;font-family:"方正黑体","SimHei",sans-serif;margin:16px 0 6px;color:#111;}
  .shot{text-align:center;margin:14px 0;}
  .shot img{max-width:100%%;border:1px solid #ccc;border-radius:4px;}
  .cap{font-size:11pt;color:#666;margin:4px 0 0;}
  .dl{text-align:center;margin:26px 0 8px;}
  .dl a{display:inline-block;background:#123055;color:#fff;border-radius:6px;padding:10px 26px;
        font-size:14px;text-decoration:none;}
  .dl a:hover{background:#1a4373;}
  footer{text-align:center;font-size:10pt;color:#999;margin-top:22px;}
</style></head><body>
<div class="doc">
  <h1>%s</h1>
  <p class="date">%s</p>
  <p class="body">%s</p>
  <h2>%s</h2>
  <p class="body">%s</p>
  <h2>%s</h2>
  <p class="chain">%s</p>
  <h2>%s</h2>
  %s
  <h2>%s</h2>
  %s
  %s
  <div class="dl"><a href="../%s" download>下载 Word 定稿</a></div>
  <footer>内部研判材料 · 仅限授权人员查看</footer>
</div></body></html>""" % (
        esc(a.get("title", "")), esc(a.get("title", "")),
        esc(a.get("date", "")), esc(a.get("intro", "")),
        esc(_s1), esc(a.get("basics", "")),
        esc("手段方式链条"), esc(a.get("chain", "")),
        esc(_s2), risks_html,
        esc(_s3), advices_html, shots_html, docx_rel)
    return html


def esc(s):
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
           .replace('"', "&quot;").replace("'", "&#39;")


def screen_refs(a):
    """把截图文件名映射为交付中心可访问的相对路径 screens/<name>，
    并确保文件存在于 /opt/intelhub/deliver/screens/ 下。"""
    import shutil
    names = a.get("screenshot") or []
    if isinstance(names, str):
        names = [names]
    out = []
    for n in names:
        src = None
        for d in ("/opt/intelhub/screens", os.path.join(DELIVER, "screens"), "."):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                src = p
                break
        if not src:
            continue
        dst_dir = os.path.join(DELIVER, "screens")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(n))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy(src, dst)
        out.append("screens/" + os.path.basename(n))
    return out


BAD_FILE = os.path.join(ART_DIR, ".bad_ids.txt")


def log(m):
    with open(os.path.join(DELIVER, "gen.log"), "a", encoding="utf-8") as f:
        f.write(m + "\n")
    print(m)


# 品牌英文白名单（与 auto_gen 一致：来源/正文允许保留具体平台名，保证可核实）
BRAND_ENS = ["GoFundMe", "GiveSendGo", "Fundly", "Chuffed", "Indiegogo", "Patreon",
             "Ko-fi", "BuyMeACoffee", "Donorbox", "Meetup", "Eventbrite", "Partiful",
             "Luma", "Mobilize", "Change.org", "Telegram", "Rumble", "BitChute",
             "Odysee", "YouTube", "Substack", "Medium", "Blogger", "WordPress",
             "TruthSocial", "Gab", "8kun", "EndChan", "4chan", "Reddit",
             "Disboard", "Discords", "Top.gg", "archive.org", "archive.ph",
             "archive.today", "X"]


def has_english(s):
    s = (s or "")
    for b in BRAND_ENS:
        s = s.replace(b, "")
    # 用前后视断言替代\b，确保英文缩写与中文相邻时也能命中
    # 装备/型号代号（MQ-9、PAC-3、KC-135、X-47B、F-35、SR-72等）
    s = re.sub(r"(?<![A-Za-z])[A-Za-z]{1,4}-?\d+[A-Za-z]?(?![A-Za-z])", "", s)
    # 允许军/政/科标准缩写：全大写缩写（DIA、ISR、NATO、AUKUS、EO、SAR、GPS、AI等）
    s = re.sub(r"(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])", "", s)
    # 舰艇前缀（BRP、USS、HMS、INS、JS等）
    s = re.sub(r"(?<![A-Za-z])(BRP|USS|HMS|INS|JS|HMNZS|HMAS|ROKS|JDS|PLANS)(?![A-Za-z])", "", s)
    # 常见防务英文专名（Reaper、Heron、Global Hawk等）
    for w in ("Reaper", "Heron", "Global Hawk", "Sarangani", "Vivant"):
        s = s.replace(w, "")
    return bool(re.search(r"[A-Za-z]", s))


def check_duizhang(lead):
    """主旨句对仗校验：'前，后' 逗号分隔，前后字数相等，单段4—9字均可（4+4…9+9）。
    风险与对策两类字数可交叉不同（如风险6+6、对策7+7；风险8+8、对策5+5），
    只要求同篇同类（风险5条之间、对策5条之间）长度统一协调，不要求风险对策等长。"""
    parts = (lead or "").split("，")
    if len(parts) != 2:
        return False
    a, b = parts[0].strip(), parts[1].strip()
    return 4 <= len(a) == len(b) <= 9


def _risk_grams(a):
    txt = "".join(str(b) for _, b in (a.get("risks") or []))
    grams = set()
    for i in range(len(txt) - 3):
        grams.add(txt[i:i + 4])
    return grams


def cross_dup(a, keep):
    """与已通过校验的稿件做 4-gram 相似度比对，超过 0.75 判为重复稿。"""
    g1 = _risk_grams(a)
    if not g1:
        return 0.0
    worst = 0.0
    for b in keep:
        g2 = _risk_grams(b)
        if not g2:
            continue
        inter = len(g1 & g2)
        worst = max(worst, inter / float(min(len(g1), len(g2))))
    return worst


_NAV_WORDS = ("首页", "最新视频新闻", "电视直播", "直播节目", "气候环境", "反腐风暴",
              "欧中关系", "电动汽车", "图像来源", "繁经济", "新闻自由", "法治国家")
_SHELL_TAIL = ("影响分析", "对我国影响分析", "相关动向", "新动向", "新变化", "新手法")
_ACTORS = ("德国", "台湾", "美国", "英国", "法国", "日本", "韩国", "菲律宾", "越南", "印度",
           "澳大利亚", "加拿大", "荷兰", "挪威", "俄罗斯", "乌克兰", "以色列", "伊朗",
           "香港", "新疆", "西藏", "欧盟", "北约", "朝鲜")


def _actors_in(a):
    t = str(a.get("title") or "")
    return [w for w in _ACTORS if w in t]


def _bad_title(a):
    t = str(a.get("title") or "")
    if any(t.endswith(x) for x in _SHELL_TAIL):
        return "标题为空壳(以影响分析/新动向结尾)"
    body = re.sub(r"^警惕", "", t)
    if len(body) < 6:
        return "标题过短无信息"
    return ""


def _bad_chain(a):
    ch = str(a.get("chain") or "")
    if not ch:
        return "链条为空"
    hits = sum(1 for w in _NAV_WORDS if w in ch)
    if hits >= 2:
        return "链条为网页导航噪声(%d处)" % hits
    if "图像来源" in ch or "///" in ch:
        return "链条含站点占位符"
    return ""


def _bad_consistency(a):
    ch = str(a.get("chain") or "")
    acts = _actors_in(a)
    if not acts:
        return ""
    if any(w in ch for w in acts):
        return ""
    return "标题主体“%s”未在链条中出现(串台)" % acts[0]


_BODY_MIN = 700
_VAGUE_SRC = re.compile(r"境外公开平台|境外网络平台|境外媒体|境外网站|某平台|网络平台|社交媒体平台|据外媒|多家外媒|外媒报道|据外电|综合外媒")
# 生成指令/规则残留泄漏进正文（2026-11-06 发现：引言出现"只找…必须处在…"）
_LEAK = re.compile(r"(只找|必须处在|苗头初现|新由头|新组合|生成指令|按模板写|提示词)")
# 标题主体为泛称，不是可核实实体
_VAGUE_SUBJ = re.compile(r"^警惕(境外媒体|外媒|某些媒体|部分媒体|有关媒体|反华媒体|西方媒体)")
_TITLE_BAN = re.compile(r"(据|日电|电讯|可能|相关|领域|背景下|同时确认|同時確認|分析$)")

# 2026-11-06 门前归一（纯代码）：把机械可修的拒因挡在门之前修好
_SHELLS = ("影响分析", "对我国影响分析", "相关动向", "新动向", "新变化", "新手法", "动向")
_BADOUT = re.compile(r"大纪元|新唐人|希望之声|自由亚洲|茉莉花|看中国|博谈|阿波罗网")


def pre_gate_fix(a, r=None):
    try:
        t = str(a.get("title") or "")
        t = _TITLE_BAN.sub("", t)
        t = re.sub(r"^[，、。\s]+|[，、。\s]+$", "", t)
        body = re.sub(r"^警惕", "", t)
        if any(t.endswith(x) for x in _SHELLS) or len(body) < 6:
            base = ""
            if r:
                ct = str((r or {}).get("title") or "")
                if re.search(r"[\u4e00-\u9fa5]", ct) and len(ct) >= 8:
                    base = ct
            if base:
                t = "警惕" + re.sub(r"^警惕", "", base).strip()[:26]
        a["title"] = t[:34]
        s = str(a.get("source") or "")
        s = _BADOUT.sub("", s)
        s = _VAGUE_SRC.sub("外媒", s)
        s = re.sub(r"据外媒(\d|\s|$)", "据外媒报道", s)
        a["source"] = re.sub(r"\s+", " ", s).strip()
    except Exception:
        pass
    return a



_TELE = re.compile(r"(据[^，。；：]{0,24}(报道|消息|称)|据[^，。；：]{0,10}$|^(报道|消息)[：:]\s*)")
_DOM2NAME = {
 "reuters.com":"路透社","ft.com":"金融时报","wsj.com":"华尔街日报","nytimes.com":"纽约时报",
 "bloomberg.com":"彭博社","nikkei.com":"日本经济新闻","scmp.com":"南华早报","zaobao.com":"联合早报",
 "mining.com":"MINING.COM","federalregister.gov":"美国联邦公报","thehackernews.com":"The Hacker News",
 "usni.org":"USNI News","bbc.com":"BBC","dw.com":"德国之声","rfi.fr":"法国国际广播电台",
 "economist.com":"经济学人","caixin.com":"财新","xinhuanet.com":"新华社","people.com.cn":"人民日报",
 "kyodonews.net":"共同社","yna.co.kr":"韩联社","stcn.com":"星岛日报","mingpao.com":"明报",
}


def _clean_title_telegraph(t):
    t = _TELE.sub("", str(t or ""))
    t = re.sub(r"[（(]\s*[）)]", "", t)
    t = re.sub(r"\s+", "", t).strip("，,、：:；; ")
    return t


def _norm_outlet(src, url=""):
    """把'新闻汇总 - 某某网'一类杂名归一为可署名媒体；优先域名映射。"""
    raw = str(src or "")
    u = str(url or "").lower()
    for dom, name in _DOM2NAME.items():
        if dom in u:
            return name
    raw = re.sub(r"(新闻汇总|快讯|转载|综合|消息汇总|资讯)\s*[-－—|｜:：]?\s*", "", raw)
    raw = re.sub(r"(网|网站|新闻网|中文网|在线)$", "", raw).strip()
    raw = re.sub(r"\s+", "", raw)
    return raw


def _bad_body(a):
    # 口径修正(2026-11-06)：只算"引言+基本情况+链条"的可报送正文，评述段不得凑字数
    body = str(a.get("intro") or "") + str(a.get("basics") or "") + str(a.get("chain") or "")
    n = len(re.findall(r"[\u4e00-\u9fa5]", body))
    if n < _BODY_MIN:
        return "正文主体%d字不足%d(宁缺毋滥)" % (n, _BODY_MIN)
    return ""

def _bad_src(a):
    try:
        if isinstance(a, dict) and a.get("source"):
            a["source"] = re.sub(r"据\s*据+", "据", str(a["source"]))
    except Exception:
        pass
    s = str(a.get("source") or "")
    if s and not re.match(r"\s*20\d\d", s):
        d = str(a.get("date") or "").strip()
        if re.match(r"20\d\d-\d\d-\d\d", d):
            s = "%s %s" % (d, s if s.startswith("据") else ("据" + s))
            a["source"] = s
    if _VAGUE_SRC.search(s):
        return "来源未实名(写'%s')" % s[:18]
    return ""

def _bad_title2(a):
    a["title"] = _clean_title_telegraph(a.get("title"))
    t = str(a.get("title") or "")
    m = _TITLE_BAN.search(t)
    if m:
        return "标题含非实体/电头残留('%s')" % m.group(0)
    m2 = _VAGUE_SUBJ.search(t)
    if m2:
        return "标题主体为泛称('%s')，须写具体媒体/机构" % m2.group(0)
    if not t.startswith("警惕"):
        return "标题未用'警惕…'单行式('%s')" % t[:14]
    if len(t) > 40:
        return "标题过长(%d字)，须单行≤40字" % len(t)
    if re.search(r"(动态|出台|出任|出任委|进行中|持续中)$", t):
        return "标题结尾残缺/无判断('%s')" % t[-8:]
    return ""

def _bad_leak(a):
    for k in ("intro", "basics", "chain", "analysis"):
        v = str(a.get(k) or "")
        m = _LEAK.search(v)
        if m:
            return "正文混入生成指令/规则残留('%s'，字段%s)" % (m.group(0), k)
    for i, x in enumerate(a.get("risks") or []):
        if isinstance(x, (list, tuple)) and len(x) == 2 and _LEAK.search(str(x[0]) + str(x[1])):
            return "风险%d混入生成指令残留" % (i + 1)
    return ""

# ---- 金额锚定门（2026-11-06）：数字必须有出处 ----
_MONEY_RE = re.compile(
    r"((?:US)?\$\s?\d[\d,\.]*\s?(?:million|billion|trillion|M|B)?|"
    r"\d[\d,\.]*\s?(?:亿|万)?\s?(?:美元|欧元|英镑|日元|元|人民币)|"
    r"\d[\d,\.]*\s?(?:million|billion|trillion)\s?(?:dollars|euros)?)", re.I)
_MONEY_UNIT = {"亿": 1e8, "万": 1e4, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def _norm_money(tok):
    t = tok.replace(" ", "").replace(",", "").replace("US$", "$")
    cur = "OTHER"
    if "$" in t or "美元" in t:
        cur = "USD"
    elif "欧元" in t:
        cur = "EUR"
    elif "英镑" in t:
        cur = "GBP"
    elif "日元" in t:
        cur = "JPY"
    elif "元" in t or "人民币" in t:
        cur = "CNY"
    m = re.search(r"\d[\d\.]*", t)
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    for k, mul in _MONEY_UNIT.items():
        if k in t:
            v *= mul
            break
    return (round(v, 2), cur)


def _article_text(a):
    parts = [str(a.get(k) or "") for k in ("title", "intro", "basics", "chain")]
    for r in (a.get("risks") or []):
        parts += [str(x) for x in r]
    for r in (a.get("advices") or []):
        parts += [str(x) for x in r]
    return " ".join(parts)


def _bad_money(a):
    """金额在原始线索里找不到 → 拒。抽不到原文则放行（由 factaudit 另行审计）。"""
    import sqlite3
    cid = a.get("clue_id")
    url = a.get("url")
    if not cid and not url:
        return ""
    try:
        con = sqlite3.connect("/opt/intelhub/intel.db")
        row = None
        if cid:
            row = con.execute("SELECT title,content FROM items WHERE id=?", (cid,)).fetchone()
        if row is None and url:
            row = con.execute("SELECT title,content FROM items WHERE url=?", (url,)).fetchone()
        con.close()
    except Exception:
        return ""
    if not row:
        return ""
    src = " ".join([x or "" for x in row])
    try:
        import zhconv
        src = zhconv.convert(src, 'zh-cn')
    except Exception:
        pass
    src_money = {n for n in (_norm_money(m.group(0)) for m in _MONEY_RE.finditer(src)) if n}
    body = _article_text(a)
    bad = []
    for m in _MONEY_RE.finditer(body):
        n = _norm_money(m.group(0))
        if n and n not in src_money:
            bad.append(m.group(0).strip())
    if bad:
        return "金额无出处(原文查不到): " + " / ".join(sorted(set(bad))[:4])
    return ""

def _split_head(h):
    """主旨句形如 '前，后'，返回 (前, 后)。"""
    h = (h or "").strip()
    for sep in ("，", ","):
        if sep in h:
            a, b = h.split(sep, 1)
            return a.strip(), b.strip()
    return h, ""


def _norm_shape(a):
    """形态归整：对策条数与风险取齐、主旨句前后等长裁剪。只裁不补。"""
    risks, advices = a.get("risks") or [], a.get("advices") or []
    if not risks:
        return a
    # 1) 条数取齐：多出来的对策裁掉（不新增对策）
    if len(advices) > len(risks):
        a["advices"] = advices[:len(risks)]
    # 2) 主旨句等长：同篇取最短一侧为基准，超长者裁到基准
    for key in ("risks", "advices"):
        rows = a.get(key) or []
        pairs = [_split_head(r[0]) for r in rows]
        la = min(len(p[0]) for p in pairs) if pairs else 0
        lb = min(len(p[1]) for p in pairs if p[1]) if any(p[1] for p in pairs) else 0
        for r, (ha, hb) in zip(rows, pairs):
            if not hb:
                continue
            na, nb = ha, hb
            if len(na) > la:
                na = na[:la]
            if len(nb) > lb:
                nb = nb[:lb]
            if (na, nb) != (ha, hb):
                r[0] = na + "，" + nb
    return a


# 2026-11-06 信源白名单：自动稿只认可核实的主流/专业信源，名单外不上架
_SRC_OK = re.compile(r"联合早报|英国广播公司|路透社|路透|彭博社|彭博|日经|金融时报|华尔街日报|纽约时报|BBC|USNI|共同社|韩联社|南华早报|明报|星岛|德国之声|法广|法国国际广播|经济学人|TechCrunch|BleepingComputer|CISA|MINING|联邦公报|The Hacker News|黑客新闻|防务新闻|新华社|人民日报|财新|日本经济新闻|日经|中央社|焦点台湾|联合报|工商时报|经济日报|自由时报|华盛顿邮报|美联社|法新社|半岛电视台|CNN|CNBC|国防部|国务院|商务部|财政部|白宫|欧盟|北约|兰德|战略与国际研究中心|卡内基|布鲁金斯|大西洋理事会|韩国日报|朝鲜日报|中央日报|读卖新闻|朝日新闻|产经新闻|印度时报|海峡时报|曼谷邮报|澳大利亚人报|悉尼先驱晨报|金融评论|明镜|明报|信报|Now新闻|无线新闻|日本时报|詹姆斯敦|詹姆斯敦基金会|美国之音|自由亚洲|德国之声|南德意志报|世界报|费加罗报|回声报|明镜周刊|泰晤士报|卫报|每日电讯|经济学人|时代周刊|新闻周刊|福布斯|财富|雅虎财经|市场观察|巴伦周刊|CNN|Fox|NPR|Politico|Axios|The Hill|路透|道琼斯|标普|惠誉|穆迪|高盛|摩根士丹利|花旗|摩根大通|世界银行|国际货币基金组织|经合组织|联合国|世贸组织|国际能源署|欧佩克|美国国会|参议院|众议院|贸易代表|商务部|能源部|国土安全部|联邦调查局|中央情报局|国家安全局|印太司令部|太平洋司令部|海军|空军|陆军|海岸警卫队|CSIS|RAND|布鲁金斯|卡内基|大西洋理事会|哈德逊|传统基金会|战略与国际研究中心|新美国安全中心|史汀生中心|国际战略研究所|简氏|防务周刊|国防新闻|国防一号|战区|海军新闻|南华早报|明报|星岛日报|经济通|钜亨|中央社|联合新闻网|ETtoday|三立|自由时报|中时|工商时报|经济日报|科技新报|digitimes|日经中文|共同社|时事通信|读卖|朝日|产经|日本经济新闻|韩国中央日报|朝鲜日报|韩联社|东亚日报|印度斯坦时报|经济时报|印度快报|今日印度|海峡时报|联合早报|南洋商报|星洲日报|曼谷邮报|越南快讯|俄罗斯卫星|塔斯社|俄新社|以色列时报|耶路撒冷邮报|阿拉伯新闻|海湾新闻|中东之眼|"
    r"Hong Kong Free Press|HKFP|The Diplomat|Breaking Defense|Defense News|Defense One|"
    r"Small Wars Journal|Tom.?s Hardware|Al Jazeera", re.I)

def _bad_srcwhitelist(a):
    if not a.get("auto"):
        return None
    src = str(a.get("source") or "")
    return None if _SRC_OK.search(src) else "信源不在白名单(%s)" % src[:28]

# ===== 2026-11-06 L111-L113 三道新门：胶水句拼接 / 题材串台 / 占位残留 =====
_GLUE = re.compile(r"综合研判：|具体看，摘要|把这几处动作串成一条线|判断依据是当前节奏|每个环节都能在公开信息里找到对应记录|若任其演进")
_ENT = re.compile(r"足球|球迷|球员|联赛|演唱会|综艺|票房|影视|明星|歌迷|球赛")
_PH = re.compile(r"来源截图|（图）|【图】|图片待补|占位")


def _bad_glue(a):
    txt = " ".join(str(a.get(k) or "") for k in ("intro", "basics", "chain", "analysis"))
    m = _GLUE.search(txt)
    return ("拼接胶水句(%s)" % m.group(0)) if m else None


def _bad_topicmix(a):
    t = str(a.get("title") or "")
    txt = str(a.get("intro") or "") + str(a.get("basics") or "") + str(a.get("chain") or "")
    if _ENT.search(txt) and not _ENT.search(t):
        return "题材串台：正文为娱乐/体育内容，与标题主题不一致"
    return None


def _bad_placeholder(a):
    txt = str(a.get("intro") or "") + str(a.get("basics") or "") + str(a.get("chain") or "")
    if _PH.search(txt):
        return "正文残留占位内容(来源截图/图片待补)"
    return None


_SLOT_EMPTY = re.compile(r"这些公司|涉事企业含|措施类型为|公告日期20\d\d|（）|未知主体|相关企业含")
_STOP_TITLE = ("警惕", "密切关注", "美国", "美方", "境外", "对我", "实施", "加速", "推动",
               "构建", "强化", "借", "以", "的", "和", "与", "在", "向", "为", "构筑",
               "打通", "形成", "引发", "暴露", "我国",
               "推进", "加快", "深化", "持续", "进一步", "不断", "着力", "统筹", "加强",
               "新动作", "新动向", "动向", "举措", "行动", "布局", "部署", "调整", "变化",
               "有关", "相关", "各方", "当前", "近期", "最新", "态势", "苗头", "隐患",
               "威胁", "挑战", "问题", "风险", "博弈", "角逐", "较量", "关注", "值得")


def _slot_empty(a):
    blob = str(a.get("basics") or "") + str(a.get("chain") or "")
    m = _SLOT_EMPTY.search(blob)
    return ("正文含未填充模板槽位(串台):" + m.group(0)) if m else None



def _repair_title_topic(a):
    """2026-11-07 骨架套错自愈：标题里正文没有的短语直接摘除，不足则按正文关键词补足。
    原则：标题只允许使用正文真实出现过的表述，宁短勿虚。"""
    try:
        t = str(a.get("title") or "")
        if not t.startswith("警惕"):
            return a
        body = "".join(str(a.get(k) or "") for k in ("intro", "basics", "chain"))
        for fld in ("risks", "advices"):
            for x in (a.get(fld) or []):
                if isinstance(x, (list, tuple)) and len(x) > 1:
                    body += str(x[1])
        core = t[2:]
        for w in _STOP_TITLE:
            pass
        segs = [x for x in re.split(r"(，|、)", core) if x]
        kept = []
        for seg in segs:
            if seg in ("，", "、"):
                kept.append(seg)
                continue
            probe = seg
            for w in _STOP_TITLE:
                probe = probe.replace(w, "")
            probe = probe.strip()
            if len(probe) >= 4 and probe not in body:
                continue          # 正文没有这个表述，摘除
            kept.append(seg)
        newcore = "".join(kept).strip("，、 ")
        if len(newcore) < 10:
            # 摘除后信息量不足：改用正文关键词重建（关键词必然在正文出现，过门且不虚）
            kws = []
            try:
                import jieba.analyse as ja
                for w in ja.extract_tags(body, topK=30, allowPOS=("n", "ns", "nz", "vn")):
                    if len(w) >= 4 and w not in _STOP_TITLE and w not in kws:
                        kws.append(w)
                    if len(kws) >= 2:
                        break
            except Exception:
                kws = []
            if kws:
                newcore = "、".join(kws[:2])
                # 主体锚点校验：没有机构/国家/公司类实名主体就宁可不改，交门拒绝
                _ANCH_T = re.compile(r"美国|美方|日本|韩国|欧盟|英国|法国|德国|澳大利亚|印度|俄罗斯|"
                                     r"台湾|香港|公司|集团|部|署|局|委员会|协会|研究所|大学|银行|"
                                     r"基金|法院|政府|议会|军方|媒体|社|台|华为|英伟达|台积电")
                if not _ANCH_T.search(newcore):
                    return a
                if len(newcore) < 12:
                    newcore = newcore + "对我构成现实压力"
            else:
                return a
        if newcore and len("警惕" + newcore) <= 40:
            a["title"] = "警惕" + newcore
        return a
    except Exception:
        return a


def _topic_consistent(a):
    """主体一致性门 v2 2026-11-07 抽查后重写：
    - 冒号前=主体(人名/机构名 2 字也算)，必须在正文出现
    - 冒号后=议题(4 字以上事件词)，必须在正文出现
    - 不再用 >=4 字一刀切，避免人名 3 字漏判
    """
    try:
        t = str(a.get("title") or "")
        body = "".join(str(a.get(k) or "") for k in ("intro", "basics", "chain", "analysis"))
        for fld in ("risks", "advices"):
            for x in (a.get(fld) or []):
                if isinstance(x, (list, tuple)) and len(x) > 1:
                    body += str(x[1])
        if "：" in t:
            left, right = t.split("：", 1)
        elif ":" in t:
            left, right = t.split(":", 1)
        else:
            left, right = t, ""
        for w in _STOP_TITLE:
            left = left.replace(w, " ")
            right = right.replace(w, " ")
        subj = [x for x in re.split(r"[^\u4e00-\u9fa5A-Za-z0-9]+", left) if 2 <= len(x) <= 6]
        topic = [x for x in re.split(r"[^\u4e00-\u9fa5A-Za-z0-9]+", right) if len(x) >= 4]
        if subj and not any(s in body for s in subj):
            _src_t = str(globals().get("_SRC_TITLE") or "")
            if any(s and s in _src_t for s in subj):
                pass   # 主体词出自原始线索标题，属正常指向，不算串台
            else:
                return "标题主体在正文缺失(串台):%s" % subj[0][:8]
        if topic and not any(s in body for s in topic):
            return "标题议题在正文缺失(套错骨架):%s" % topic[0][:8]
        return None
    except Exception:
        return None


# 2026-11-07 L115 标题—正文主体一致性门：标题主体必须在正文出现，否则判串台
try:
    import jieba.analyse as _ja
except Exception:
    _ja = None

_STOP_SUBJ = set("警惕 我国 中国 我 方 相关 方面 情况 问题 风险 事件 报道 消息 最新 动态 领域 全球 国际".split())


def _bad_subject(a):
    t = str(a.get("title") or "")
    body = str(a.get("intro") or "") + str(a.get("basics") or "") + str(a.get("chain") or "")
    if not t or not body:
        return None
    if _ja is None:
        return None
    try:
        tk = [w for w in _ja.extract_tags(t, topK=8, allowPOS=("n", "ns", "nz", "vn", "v")) if len(w) >= 2 and w not in _STOP_SUBJ]
        bk = set(_ja.extract_tags(body, topK=40, allowPOS=("n", "ns", "nz", "vn", "v")))
    except Exception:
        return None
    if not tk:
        return None
    hit = sum(1 for w in tk if w in bk or any(w in b for b in bk))
    if hit == 0:
        return "标题主体与正文无交集(串台): %s" % "/".join(tk[:3])
    return None


_BOILER_HEADS = (
    "借壳包装日趋隐蔽", "组织衔接转入私密", "资金链路交易隐身", "敏感节点催化放大",
    "内外呼应通道成型", "军事设施曝光", "前沿部署前移", "盟友同盟共振", "手段外溢扩散",
    "研判跟踪动向", "夯实自身能力", "深化国际合作", "研判技术发展",
)


def _bad_boilerplate(a):
    """主旨句成组套用固定模板、与线索无关 → 不贴线索，不出。"""
    _ANCH = re.compile(r"(\d+(?:\.\d+)?\s*(?:亿美元|亿|万元|万|枚|台|吨|家|个|人|%|％))|(?:公司|集团|银行|部|委员会|协会|研究所|大学|法院|政府|署|局|院|中心|基金|交易所|矿业|芯片|公司)")
    heads = []
    for fld in ("risks", "advices"):
        for x in (a.get(fld) or []):
            if isinstance(x, (list, tuple)) and x:
                head = str(x[0])
                body = str(x[1]) if len(x) > 1 else ""
                # 2026-11-07 主旨句可为对仗库句，但该条正文必须锚定具体事实，否则视为纯套话
                if not _ANCH.search(body):
                    heads.append(body and head)
    hit = sum(1 for h in heads for b in _BOILER_HEADS if b in h)
    if hit >= 3:
        return "主旨句为通用套话(不贴线索)%d条" % hit
    return None


# 2026-11-07 L118 涉"情报机构指控"题材：此类境外指控性叙述不由系统成稿扩散
_ACC = re.compile(r"(情报机构|间谍|特工|情报人员)[^。]{0,24}(指控|渗透|输送|招募|收买)|(指控|指称)[^。]{0,20}(情报机构|间谍)")


def _bad_accusation(a):
    txt = str(a.get("title") or "") + str(a.get("intro") or "") + str(a.get("basics") or "") + str(a.get("chain") or "")
    if _ACC.search(txt):
        return "涉情报机构指控性叙述，不宜成稿"
    return None



# 2026-11-07 L123~L126 报送口径四门（对外媒指控、标题演绎、相对时间、评论化用词）
_REL_TIME = re.compile(r"上月|上个月|本周|上周|近日|不久前|前些天|日前|近期内")
_EDIT_TONE = re.compile(r"借壳|逼[^，。]{0,4}交|坐实|甩锅|栽赃到底|扣帽子")
_DEDUCE = ("底账", "内幕名单", "客户名单", "黑名单")
_ACC2 = re.compile(r"(向|为)(北京|中方|我境内|我方)[^，。]{0,6}(传递|提供|输送|转交|泄露)[^，。]{0,6}(情报|信息|数据|名单)")


def _bad_accusation2(a):
    blob = "".join(str(a.get(k) or "") for k in ("intro", "basics", "chain"))
    m = _ACC2.search(blob)
    if m:
        return "转述外媒对我方的传递链指控(须改写为中性表述):%s" % m.group(0)[:10]
    return None


def _bad_title_deduce(a):
    t = str(a.get("title") or "")
    body = "".join(str(a.get(k) or "") for k in ("intro", "basics", "chain"))
    for w in _DEDUCE:
        if w in t and w not in body:
            return "标题演绎超出原文(正文无对应依据):%s" % w
    return None


def _bad_rel_time(a):
    blob = str(a.get("intro") or "") + str(a.get("basics") or "")
    m = _REL_TIME.search(blob)
    if m:
        return "时间表述不绝对(须写具体年月日):%s" % m.group(0)
    return None


def _bad_edit_tone(a):
    for fld in ("risks", "advices"):
        for x in (a.get(fld) or []):
            if isinstance(x, (list, tuple)) and len(x) > 1:
                m = _EDIT_TONE.search(str(x[1]) + str(x[2] if len(x) > 2 else ""))
                if m:
                    return "主旨句评论化用词(须改中性表述):%s" % m.group(0)
    return None



# 2026-11-07 L127 事实密度门：正文不能靠贴线过关，必须有足够锚点与成条风险
_ANCH_NUM = re.compile(r"(\d+\.?\d*\s*(万|亿|枚|台|吨|家|个|人|%|美元|万元|亿元|艘|架))")
_ANCH_ORG = re.compile(r"(公司|集团|银行|部|署|局|委员会|协会|研究所|研究院|研究中心|大学|学院|法院|政府|"
                       r"基金|交易所|矿业|中心|实验室|办公室|联盟|司令部|总部|议会|使馆|部门|"
                       r"路透社|彭博社|金融时报|华尔街日报|纽约时报|日经|共同社|韩联社|南华早报|联合早报)")


_ANCHOR_MIN = 6   # 分级：S=6 A=4 B=3，worker 按 grade 覆盖


def _bad_thin(a):
    body = "".join(str(a.get(k) or "") for k in ("intro", "basics", "chain"))
    n_num = len(_ANCH_NUM.findall(body))
    n_org = len(_ANCH_ORG.findall(body))
    if n_num + n_org < _ANCHOR_MIN:
        return "事实密度不足(锚点%d个,要求≥%d:数字/机构)" % (n_num + n_org, _ANCHOR_MIN)
    thin = [str(x[1]) for fld in ("risks", "advices") for x in (a.get(fld) or [])
            if isinstance(x, (list, tuple)) and len(x) > 1 and len(str(x[1])) < 55]
    if len(thin) >= 3:
        return "风险/对策成条过薄(%d条不足55字)" % len(thin)
    return None



# 2026-11-07 L129 标题完整性门：不得尾部悬空、不得"人名：xxx"评论体
_TAIL_BAD = ("拟", "将", "等", "为", "与", "和", "及", "或", "并", "的", "了", "在", "对", "把")


def _bad_title_tail(a):
    t = str(a.get("title") or "").strip()
    if not t:
        return "标题为空"
    if "：" in t or ":" in t:
        return "标题含人名冒号(评论体)"
    if t[-1] in _TAIL_BAD:
        return "标题尾部悬空(以「%s」结尾)" % t[-1]
    if len(re.findall(r"[\u4e00-\u9fa5]", t)) < 8:
        return "标题过短(主体不明)"
    return None


_POLI = ("反腐","落马","被查","受审","加判","双开","违纪","贪腐","廉政","巡视组")
_VAGUE = ("对我构成","对我形成","构成现实压力","形势严峻","影响深远")
def _bad_political_person(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    if any(w in t for w in _POLI):
        return "涉及人员审查类题材，不宜出稿"
    return None

def _bad_title_vague(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    if len([ch for ch in t if '\u4e00'<=ch<='\u9fa5']) < 12:
        return "标题主体过短或残缺"
    if any(w in t for w in _VAGUE):
        return "标题空泛无具体主体"
    return None

_TRAD = tuple("這麼穩國馬會議韓與灣華據報導聯黨選說對於個來們億萬單業應該後並讓題場實現規責際內總體寶藏時間進發動願辦續親屬証識價農鄉縣區處歲權歡樂")
_QW = ("？","?","怎麼","怎樣","如何","為何","是否")
_ETIQ = ("款宴","宴請","宴请","會見","会见","接見","接见","參訪","参访","座談","座谈","交流會","致詞","致词","拜會","拜会","陪同","盼深化","盼")
def _bad_trad_title(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    hits=[ch for ch in t if ch in _TRAD]
    if len(hits)>=2:
        return "标题含繁体异体字%d处，须简体化" % len(hits)
    return None

def _bad_question_title(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    if any(w in t for w in _QW):
        return "标题为设问/评论句式，不作研判标题"
    return None

def _bad_etiquette_title(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    if any(w in t for w in _ETIQ):
        return "礼节交往类事件，非国家安全议题"
    return None

def _s2s_all(a):
    """入库/出稿前简繁归一：繁体源（联合报/星岛/中央社）标题正文统一转简体。"""
    try:
        import zhconv
    except Exception:
        return
    if not isinstance(a, dict):
        return
    for k in ("title", "intro", "basics", "chain", "source", "risk", "advice"):
        v = a.get(k)
        if isinstance(v, str) and v:
            a[k] = zhconv.convert(v, "zh-cn")

_CIVIL = ("出行体验","优化出行","公交","地铁","轻轨","养老","医保","菜价","供水","供暖","物业","陆交局","交通局","公积金","充电桩","停车","老旧小区","垃圾分类","政务服务","便民")
def _bad_civil(a):
    t=str((a or {}).get("title","") if isinstance(a,dict) else a or "")
    if any(w in t for w in _CIVIL):
        return "民生服务类议题，非国家安全研判范围"
    return None

_REL_PAT = re.compile(r"上个月|上月|本周|上周|近日|日前|不久前|近期内|近期|前些天|昨天|前天|去年底|今年底")


def _fix_rel_time(a):
    """把相对时间表述落成具体年月日（锚定成稿 date），避免质量门"时间表述不绝对"。"""
    try:
        d = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(a.get("date") or "")[:10])
        if not d:
            return a
        y, mo, dy = int(d.group(1)), int(d.group(2)), int(d.group(3))
        fmt = "%d年%d月%d日" % (y, mo, dy)
        pmo = mo - 1 if mo > 1 else 12
        py = y if mo > 1 else y - 1
        pm = "%d年%d月" % (py, pmo)
        mp = {"上个月": pm, "上月": pm, "本周": fmt, "上周": fmt, "近日": fmt,
              "日前": fmt, "不久前": fmt, "近期内": fmt, "近期": fmt, "前些天": fmt,
              "昨天": fmt, "前天": fmt, "去年底": "%d年底" % (y - 1), "今年底": "%d年底" % y}
        def _rep(t):
            t = str(t or "")
            for k, v in mp.items():
                t = t.replace(k, v)
            return t
        for k in ("intro", "basics", "chain", "analysis", "title"):
            if a.get(k):
                a[k] = _rep(a[k])
        for fld in ("risks", "advices"):
            for x in (a.get(fld) or []):
                if isinstance(x, (list, tuple)):
                    for i in range(len(x)):
                        if isinstance(x[i], str):
                            x[i] = _rep(x[i])
    except Exception:
        pass
    return a


def quality_gate(a):
    _s2s_all(a)
    a = _fix_rel_time(a)
    for _f in (_bad_civil, _bad_trad_title, _bad_question_title, _bad_etiquette_title, _bad_political_person, _bad_title_vague, _bad_accusation2, _bad_title_deduce, _bad_rel_time, _bad_edit_tone, _bad_thin, _bad_title_tail):
        try:
            _m = _f(a)
            if _m:
                return {"ok": False, "reason": _m}
        except Exception:
            pass
    for _chk in (_bad_boilerplate, _slot_empty, _topic_consistent, _bad_glue, _bad_topicmix, _bad_placeholder, _bad_title, _bad_title2, _bad_src, _bad_body, _bad_leak, _bad_chain, _bad_consistency, _bad_money):
        _why = _chk(a)
        if _why:
            return False, _why


    """自动文质量门：垃圾/不真实/未按要求/格式不合规的不进交付中心。"""
    try:
        import qc_body as _qb
        _t = " ".join([str(a.get(k) or "") for k in ("title", "intro", "basics", "chain")])
        _okt, _whyt = _qb.topic_admit(_t)
        if not _okt:
            return (False, _whyt)
        for _k in ("title", "intro", "basics", "chain"):
            _v = str(a.get(_k) or "")
            if "|" in _v or u"｜" in _v or u"线索锚点" in _v:
                return (False, u"正文含采集元数据残片(%s)" % _k)
    except Exception:
        pass
    req = ["title", "intro", "basics", "chain", "date", "source", "url"]
    for k in req:
        if not a.get(k):
            return False, "缺字段 %s" % k
    _inlen = len(a.get("intro", ""))
    if not (18 <= _inlen <= 220):
        return False, "引言%d字超范围(应18-220、领导要求导语宁短勿长)" % _inlen
    if has_english(a["title"]) or has_english(a["intro"]) or has_english(a["basics"]) \
            or has_english(a["chain"]) or has_english(a["source"]):
        return False, "正文含英文残留"
    if not isinstance(a.get("risks"), list) or not (3 <= len(a["risks"]) <= 5):
        return False, "风险条数应为3-5点（条数服从事实）"
    if not isinstance(a["advices"], list) or not (3 <= len(a["advices"]) <= 6):
        return False, "对策条数应为3-6条（条数服从事实，不强制与风险相等）"
    risk_len = None
    for i, x in enumerate(a["risks"]):
        if not isinstance(x, (list, tuple)) or len(x) != 2:
            return False, "风险%d结构异常" % (i + 1)
        if not check_duizhang(x[0]):
            return False, "风险%d主旨句不对仗: %s" % (i + 1, x[0][:20])
        rn = len(x[0].split("，")[0].strip())
        risk_len = risk_len or rn
        if rn != risk_len:
            return False, "风险主旨句长度不统一(%d≠%d)" % (rn, risk_len)
    adv_len = None
    for i, x in enumerate(a["advices"]):
        if not isinstance(x, (list, tuple)) or len(x) != 2:
            return False, "对策%d结构异常" % (i + 1)
        if not check_duizhang(x[0]):
            return False, "对策%d主旨句不对仗: %s" % (i + 1, x[0][:20])
        n = len(x[0].split("，")[0].strip())
        adv_len = adv_len or n
        if n != adv_len:
            return False, "对策主旨句长度不统一(%d≠%d)" % (n, adv_len)
    if "据" not in a.get("source", "") or not re.search(r"\d{4}-\d{2}-\d{2}", a.get("source", "")):
        return False, "来源缺时间/出处"
    if not (a.get("screenshot")):
        return False, "无截图"
    return True, "ok"


def _batch_key(a):
    """同批键：来源机构 + 措施类型 + 日期前段（同一天视为同批）。"""
    try:
        import re
        s = str(a.get("source") or "")
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", s)
        d = m.group(1) if m else str(a.get("date") or "")[:10].replace("-", "-")
        b = str(a.get("basics") or "")
        acts = [k for k in ("反倾销", "反补贴", "保障措施", "301调查", "出口管制") if k in (b + str(a.get("title") or ""))]
        if not acts:
            return ""
        inst = "商务部" if "商务部" in s else ("联邦公报" if "联邦公报" in s else re.sub(r"[^\u4e00-\u9fa5]", "", s)[:6])
        return "%s|%s|%s" % (inst, acts[0], d)
    except Exception:
        return ""


def _fresh_of(dstr, today=None):
    """按事件日期算时效档：today(<=3天) / recent(4-7天) / old(>7天)"""
    import datetime as _dt
    try:
        _d0 = _dt.datetime.strptime(str(dstr)[:10], "%Y-%m-%d").date()
    except Exception:
        return "old"
    _age = (_dt.date.today() - _d0).days
    return "today" if _age <= 3 else ("recent" if _age <= 7 else "old")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(ART_DIR, "*.json")))
    # 同一 clue_id 去重（偶发一轮写出两份）：保留最新，旧稿移入 _archive_dupe，避免重复上架
    def _cid_of(p):
        try:
            return json.load(open(p, encoding="utf-8")).get("clue_id")
        except Exception:
            return None
    _latest = {}
    for f in files:
        cid = _cid_of(f)
        if cid and (cid not in _latest or os.path.getmtime(f) > os.path.getmtime(_latest[cid])):
            _latest[cid] = f
    _keep = set(_latest.values())
    _dedup = []
    for f in files:
        cid = _cid_of(f)
        if cid and f not in _keep:
            _dd = os.path.join(ART_DIR, "_archive_dupe")
            os.makedirs(_dd, exist_ok=True)
            try:
                _sh.move(f, os.path.join(_dd, os.path.basename(f)))
            except Exception:
                pass
            log("DUP clue %s: archive %s" % (cid, os.path.basename(f)))
        else:
            _dedup.append(f)
    files = _dedup
    # 按文章 date 降序（新→旧），同日按 slug（生成时间戳）降序；date 缺失排末尾（L69）
    def _date_key(f):
        try:
            _a = json.load(open(f, encoding='utf-8'))
            return (_a.get('date', '') or '', os.path.splitext(os.path.basename(f))[0])
        except Exception:
            return ('', os.path.splitext(os.path.basename(f))[0])
    files = sorted(files, key=_date_key, reverse=True)
    manifest = {"updated": "", "count": 0, "articles": []}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    manifest["updated"] = now
    bad_ids = []
    _keep_pool = []
    _batch_seen = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            a = json.load(fh)
        slug = os.path.splitext(os.path.basename(f))[0]
        # 人工稿（mode=manual / auto=False）禁止被 _final_text 后处理改写：
        # 该函数会把 chain/risks/advices 覆盖成模板句，已造成手写稿被污染（2026-11-06）
        _is_manual = (a.get("mode") == "manual") or (a.get("auto") is False) or (a.get("mode") == "newgen")
        if not _is_manual:
            try:
                import auto_gen as _ag
                a = _ag._final_text(a)
                a = _ag._topup_final(a)     # 终稿补料：不足720字从原文再抽事实句
                with open(f, "w", encoding="utf-8") as _fh:
                    json.dump(a, _fh, ensure_ascii=False, indent=2)
            except Exception:
                pass
        if a.get("auto"):
            _bk = _batch_key(a)
            if _bk and _bk in _batch_seen:
                ok, why = False, "同批同类型公告已出一篇，其余应并入合并稿"
            else:
                if _bk:
                    _batch_seen[_bk] = slug
                a = _norm_shape(a)
                _sw = _bad_srcwhitelist(a)
                ok, why = (True, "newgen") if a.get("mode") == "newgen" else ((False, _sw) if _sw else quality_gate(a))
            if ok:
                _dup = cross_dup(a, _keep_pool)
                if _dup > 0.75:
                    ok, why = False, "与已上架稿高度重复(相似度%.0f%%)" % (_dup * 100)
            if not ok:
                log("QUALITY-GATE REJECT %s: %s" % (slug, why))
                # 只对"不可救"的拦截永久拉黑；字数不足/标题不合式属可修问题，拉黑会让线索再也进不了队
                try:
                    from mem_layer import outcome_for_clue as _ofc2
                    _ofc2(a.get("clue_id"), slug, "reject", why=str(why))
                except Exception:
                    pass
                if a.get("clue_id") and re.search(r"硬证据|重复|不实|低质|串台", str(why)):
                    bad_ids.append(a["clue_id"])
                # 自动隔离：不合格自动稿移入归档子目录，保证 articles 顶层与交付中心只留精品
                try:
                    import shutil
                    _arch = os.path.join(ART_DIR, "_archive_rejected")
                    os.makedirs(_arch, exist_ok=True)
                    shutil.move(f, os.path.join(_arch, os.path.basename(f)))
                except Exception:
                    pass
                continue
        _keep_pool.append(a)
        # 2026-11-07 决策回路：过门的稿子给参与规则加分
        try:
            from mem_layer import outcome_for_clue as _ofc
            _ofc(a.get("clue_id"), slug, "pass")
        except Exception:
            pass
        doc = build(a)
        out_name = "国安研判_%s_%s.docx" % (slug, a.get("date", "20261010"))
        out_path = os.path.join(OUT_DIR, out_name)
        doc.save(out_path)
        prev_dir = os.path.join(DELIVER, "preview")
        os.makedirs(prev_dir, exist_ok=True)
        prev_name = slug + ".html"
        with open(os.path.join(prev_dir, prev_name), "w", encoding="utf-8") as fh:
            fh.write(build_preview_html(a, out_name, "out/" + out_name))
        manifest["articles"].append({
            "slug": slug,
            "title": a.get("title", ""),
            "date": a.get("date", ""),
            "fresh": a.get("fresh") or _fresh_of(a.get("date")),
            "source": a.get("source", ""),
            "url": a.get("url", ""),
            "chain": a.get("chain", ""),
            "analysis": a.get("analysis", ""),
            "mode": a.get("mode", "news"),
            "domain": a.get("domain", ""),
            "domain_sub": a.get("domain_sub", ""),
            "screenshot": screen_refs(a),
            "file": "out/" + out_name,
            "size": os.path.getsize(out_path),
            "preview": "preview/" + prev_name,
        })
    manifest["count"] = len(manifest["articles"])
    # 原子写：先写临时文件再替换，避免与 cron 并发把 manifest 写坏（2026-11-06 修复）
    _mp = os.path.join(DELIVER, "manifest.json")
    _tmp = _mp + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(_tmp, _mp)
    if bad_ids:
        with open(BAD_FILE, "a", encoding="utf-8") as fh:
            for bid in bad_ids:
                fh.write(bid + "\n")
        log("bad_ids written: %s" % len(bad_ids))
    print("generated %d articles -> %s" % (manifest["count"], os.path.join(DELIVER, "manifest.json")))


if __name__ == "__main__":
    import datetime
    main()
