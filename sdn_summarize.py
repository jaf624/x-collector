# -*- coding: utf-8 -*-
"""SDN 名单确定性归纳（纯代码，不使用模型）。

输入 gov_action_collect.extract_body 的英文规整输出（每行一个条目），
用正则/查表在英文阶段完成项目、国家、涉华、中文名的结构化提取，再套模板生成连贯中文。
只有简短的动作叙述需要外部翻译后传入；所有事实均来自原文，不新增信息。"""
import re

# 项目标签 [TAG] → 中文（按标签关键字匹配，长/先特判）
PROGRAM = [
    ("VENEZUELA", u"委内瑞拉相关制裁"),
    ("CYBER", u"网络相关制裁"),
    ("PAIPA", u"知识产权保护法制裁"),
    ("DPRK", u"朝鲜相关制裁"),
    ("CUBA", u"委内瑞拉相关制裁"),  # 占位，下方覆盖
    ("TCO", u"跨国犯罪组织制裁"),
    ("IRAN", u"伊朗相关制裁"),
]
PROGRAM = [
    ("VENEZUELA", u"委内瑞拉相关制裁"),
    ("CYBER", u"网络相关制裁"),
    ("PAIPA", u"知识产权保护法制裁"),
    ("DPRK", u"朝鲜相关制裁"),
    ("CUBA", u"古巴相关制裁"),
    ("TCO", u"跨国犯罪组织制裁"),
    ("IRAN", u"伊朗相关制裁"),
]

# 英文国名/地名 → 中文（长名在前，避免子串误匹配）
COUNTRIES_EN = [
    ("United Arab Emirates", u"阿拉伯联合酋长国"),
    ("British Virgin Islands", u"英属维尔京群岛"),
    ("Virgin Islands, British", u"英属维尔京群岛"),
    ("Saint Lucia", u"圣卢西亚"),
    ("Hong Kong", u"中国香港"),
    ("United States", u"美国"),
    ("Tajikistan", u"塔吉克斯坦"),
    ("Madagascar", u"马达加斯加"),
    ("Malaysia", u"马来西亚"),
    ("Singapore", u"新加坡"),
    ("Cambodia", u"柬埔寨"),
    ("Vanuatu", u"瓦努阿图"),
    ("Panama", u"巴拿马"),
    ("Turkey", u"土耳其"),
    ("Russia", u"俄罗斯"),
    ("Greece", u"希腊"),
    ("India", u"印度"),
    ("Cuba", u"古巴"),
    ("China", u"中国"),
    ("Laos", u"老挝"),
    ("Korea", u"韩国"),
    ("Iran", u"伊朗"),
    ("Belarus", u"白俄罗斯"),
    ("Canada", u"加拿大"),
]

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# 标记行（英文）
MARK_EN = ("following individuals", "following entities", "following vessels",
           "following changes", "list updates", "unrelated administrative",
           "specially designated nationals list")
# 叙述行（英文，不是条目）
NARR_EN = ("the department", "additionally", "sign up", "office of terrorism",
           "ofac has made", "ofac is")


def _infer(ln):
    if "DOB" in ln or ("nationality" in ln and "flag" not in ln and "Vessel" not in ln):
        return u"个人"
    if "flag" in ln or "Vessel" in ln or "MMSI" in ln:
        return u"船舶"
    return u"实体"


def parse_lines(content):
    """逐行分类，返回 (叙述行, [(kind, line)])。"""
    lines = [x.strip() for x in content.replace(u"\xa0", u"\n").split(u"\n") if x.strip()]
    narr, entries, section = [], [], None
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in MARK_EN):
            if "following individuals" in low:
                section = u"个人"
            elif "following entities" in low:
                section = u"实体"
            elif "following vessels" in low:
                section = u"船舶"
            elif "following changes" in low:
                section = u"变更"
            continue
        if any(k in low for k in NARR_EN):
            narr.append(ln)
            continue
        kind = _infer(ln) if section in (None, u"变更") else section
        entries.append((kind, ln))
    return narr, entries


def entry_name(ln):
    """英文名称：第一个逗号/分号/括号前。"""
    return re.split(r",|;|\(", ln, 1)[0].strip()


def entry_name_zh(ln):
    """优先取条目自带中文名，否则回退英文名。"""
    m = re.search(r"Chinese (?:Simplified|Traditional):\s*([^)]+)\)", ln)
    if m:
        return m.group(1).strip()
    return entry_name(ln)


def entry_programs(ln):
    out = []
    for tag in re.findall(r"\[([A-Z][A-Z0-9\-]*)\]", ln):
        for key, zh in PROGRAM:
            if key in tag and zh not in out:
                out.append(zh)
    return out


def entry_countries(ln):
    out = []
    for en, zh in COUNTRIES_EN:
        if en in ln and zh not in out:
            out.append(zh)
    return out


def is_china(ln):
    if re.search(r"Chinese (?:Simplified|Traditional)", ln):
        return True
    if re.search(r"USCC|Unified Social Credit", ln):
        return True
    if re.search(r"nationality\s+China|POB[^;]*China|,\s*China;|China;", ln):
        return True
    return False


def _fmt_date(s):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s)
    if not m:
        return ""
    mon = _MONTHS.get(m.group(2))
    if not mon:
        return ""
    return u"%s年%d月%d日" % (m.group(3), mon, int(m.group(1)))


def _place(s):
    out = []
    for en, zh in COUNTRIES_EN:
        if en in s and zh not in out:
            out.append(zh)
    return out


def entry_detail(ln):
    """单条目可核实事实点，全部来自原文，不推断。"""
    bits = []
    m = re.search(r"DOB\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", ln)
    if m:
        d = _fmt_date(m.group(1))
        if d:
            bits.append(u"出生于" + d)
    mp = re.search(r"POB\s+([^;]+);", ln)
    if mp:
        p = _place(mp.group(1))
        if p:
            bits.append(u"出生地" + u"、".join(p))
    mn = re.search(r"nationality\s+([^;]+);", ln)
    if mn:
        p = _place(mn.group(1))
        if p:
            bits.append(u"国籍" + u"、".join(p))
    npass = len(re.findall(r"Passport\s+", ln))
    if npass:
        bits.append(u"被点名%d本护照" % npass)
    if "National ID" in ln:
        bits.append(u"国民身份证被点名")
    m = re.search(r"Organization Established Date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", ln)
    if m:
        d = _fmt_date(m.group(1))
        if d:
            bits.append(u"成立于" + d)
    mf = re.search(r"([A-Za-z ]+?)\s+flag", ln)
    if mf:
        p = _place(mf.group(1))
        if p:
            bits.append(u"挂" + u"、".join(p) + u"船旗")
    my = re.search(r"Vessel Year of Build\s+(\d{4})", ln)
    if my:
        bits.append(u"%s年建造" % my.group(1))
    if "IMO" in ln:
        bits.append(u"IMO编号被点名")
    ncoin = len(re.findall(r"Digital Currency Address", ln))
    if ncoin:
        bits.append(u"被标注%d个数字货币地址" % ncoin)
    if "USCC" in ln or "Unified Social Credit" in ln:
        bits.append(u"被标注统一社会信用代码")
    if "secondary sanctions" in ln.lower():
        bits.append(u"被提示二级制裁风险")
    if "false flag" in ln.lower():
        bits.append(u"涉假旗航行")
    if "Registration Number" in ln or "Tax ID" in ln:
        bits.append(u"登记注册号被点名")
    ml = re.search(r"Linked To:\s*([^)]+)\)", ln)
    if ml:
        bits.append(u"关联" + ml.group(1).strip()[:36])
    return bits


def build_summary(en_content, action_zh=u""):
    """对英文正文生成连贯中文归纳；action_zh 为动作叙述的中文翻译。"""
    narr, entries = parse_lines(en_content)
    persons = [l for k, l in entries if k == u"个人"]
    orgs = [l for k, l in entries if k == u"实体"]
    ships = [l for k, l in entries if k == u"船舶"]
    china = [l for k, l in entries if is_china(l)]
    countries, programs = [], []
    for k, l in entries:
        for c in entry_countries(l):
            if c not in countries:
                countries.append(c)
        for p in entry_programs(l):
            if p not in programs:
                programs.append(p)

    paras = []
    if action_zh.strip():
        paras.append(action_zh.strip())
    scale = []
    if persons:
        scale.append(u"%d名个人" % len(persons))
    if orgs:
        scale.append(u"%d家实体" % len(orgs))
    if ships:
        scale.append(u"%d艘船舶" % len(ships))
    if scale:
        s = u"本次名单更新共列名" + u"、".join(scale)
        if countries:
            s += u"，地域上涉及%s等" % u"、".join(countries[:7])
        paras.append(s + u"。")
    if china:
        paras.append(u"其中涉华对象共%d个，是本次动作需重点关注的部分，具体如下。" % len(china))
        for l in china:
            line = u"——" + entry_name_zh(l)
            bits = entry_detail(l)
            if bits:
                line += u"，" + u"、".join(bits)
            paras.append(line + u"。")
    low = en_content.lower()
    means = []
    if "digital currency" in low:
        means.append(u"标注数字货币地址")
    if "false flag" in low:
        means.append(u"点名假旗航行")
    if "secondary sanctions" in low:
        means.append(u"提示二级制裁风险")
    tail = u""
    if programs:
        tail = u"相关动作依据%s等项目" % u"、".join(programs)
    if means:
        tail += (u"，并通过%s强化追踪" % u"、".join(means)) if tail else u"通过%s强化追踪" % u"、".join(means)
    if tail:
        paras.append(tail + u"，制裁链条和外溢风险需持续跟踪评估。")
    return u"\n".join(paras)


_ACTION_EN = ("ofac is", "ofac has", "the department", "additionally")
_JUNK_EN = ("sign up", "office of terrorism")


def action_lines(en):
    """挑出值得翻译的动作叙述句，排除行政碎片。"""
    narr, _ = parse_lines(en)
    out = []
    for x in narr:
        low = x.lower()
        if any(k in low for k in _JUNK_EN):
            continue
        if any(k in low for k in _ACTION_EN) and x not in out:
            out.append(x)
    return out


if __name__ == "__main__":
    import json
    en = open("/tmp/full_en.txt").read()
    out = build_summary(en)
    print(u"归纳汉字数 %d" % len(re.findall(u"[一-鿿]", out)))
    print(out)
