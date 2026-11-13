# -*- coding: utf-8 -*-
"""
seven_line.py —— 7 条生成流分线核心（纯代码：正则/查表/可校验/可改，不用模型）
职责：
  1) route_style       在已过题材门的合格安全料内部分到 L1-L7（标题优先，不在选料前做）
  2) build_title_style  按线构造标题（规则表优先），过 title_ok_style 且核心词在正文
  3) build_intro_style  按线引言模板
  4) 6 条风险/对策主旨句与第 6 条 body（领域驱动，条数尽量 6、服从事实）
样式(style)决定标题/引言/小节/配额；领域(domain)决定对仗主旨句与 body 模板。
"""
import re

# 服务器模块延迟/容错加载，保证本地可独立测试、服务器可正常运行
try:
    import qc_body
except Exception:
    qc_body = None
try:
    import flow_rules as fr
except Exception:
    class _Fr(object):
        @staticmethod
        def to_simplified(x):
            return x or ''
    fr = _Fr()


def _simpl(x):
    return fr.to_simplified(x or '')


# ================================================================ 样式元数据
# code: (名称, 配额, sentence_type, 三小节标题, 风险目标, 对策目标)
STYLES = {
    "L1": (u"警惕型", 0.55, u"警惕式",
           [u"一、基本情况", u"二、风险隐患", u"三、对策建议"], 6, 6),
    "L2": (u"综合分析长题", 0.08, u"斥资动向式",
           [u"一、斥资动向", u"二、对我影响", u"三、应对建议"], 6, 6),
    "L3": (u"影响风险分析", 0.12, u"影响分析式",
           [u"一、事件概况", u"二、对我国影响", u"三、应对建议"], 6, 6),
    "L4": (u"疑似型", 0.08, u"疑似苗头式",
           [u"一、线索苗头", u"二、甄别研判", u"三、预警建议"], 6, 6),
    "L5": (u"网传型", 0.0, u"网传爆料式",
           [u"一、网传内容", u"二、核实与真相", u"三、处置建议"], 6, 6),
    "L6": (u"观察研判画像", 0.07, u"态势综合式",
           [u"一、总体态势", u"二、主要动向", u"三、趋势研判与建议"], 6, 6),
    "L7": (u"陈述研判", 0.10, u"陈述研判式",
           [u"一、基本情况", u"二、风险研判", u"三、对策建议"], 6, 6),
}
STYLE_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]

# ================================================================ 路由信号（标题优先·双语·收紧）
# L5 网传/视频流传
RE_NET = re.compile(
    u"网传|网络流传|网上流传|视频流传|视频显示|社交平台流传|开始流传|疯传|"
    u"circulating|viral|video shows|footage|in a video|emerges", re.I)
# 正文端强网传标记（标题无网传词时兜底，避免普通新闻的 attack 等词先命中 L1）
RE_NET_STRONG = re.compile(
    u"视频流传|网络流传|社交平台|疯传|未公布.{0,4}型号|型号.{0,4}待核实|"
    u"new footage|circulating|viral|video circulating|footage.{0,12}(emerg|show|highlight)", re.I)
# L4 强未坐实（去掉"被指/涉嫌/指控"等新闻弱词，避免确定事件被引用语带偏）
RE_SUSPECT = re.compile(
    u"疑似|尚未证实|未经证实|未获证实|还未证实|尚未坐实|未.{0,2}证实|待核实|待证实|风波|"
    u"unconfirmed|suspected|alleged|rumored|rumoured|not verified|mysterious", re.I)
RE_CONFIRMED = re.compile(
    u"已起诉|已宣判|已判刑|已确认|官方证实|调查证实|罪名成立|已被定罪|已逮捕|"
    u"confirmed|verified|convicted", re.I)
# 匿名信源/备忘录式未坐实情报指控（须挂来源、按疑似处理，不能当确定事实）
RE_UNVERIFIED_INTEL = re.compile(
    u"据.{0,14}(透露|消息人士|知情人士|简报|备忘录)|备忘录.{0,10}(援引|称|指|传阅)|"
    u"情报(官员|部门|机构|界).{0,8}(怀疑|认为|指|指控)|"
    u"according to.{0,24}(memo|officials|briefing|sources)|"
    u"memo.{0,16}(circulat|said|accus|according)", re.I)
# L7 客观个案（强标记，优先于 L2）
RE_STATE = re.compile(
    u"记录显示|采购记录|数据显示|调查发现|核查发现|文件显示|以.{2,8}为例|"
    u"records show|data show|investigation finds|case study|bought|despite.{0,12}blacklist", re.I)
# L2 明确金额（必须有具体数字金额；单纯订单/合同无金额不构成 L2）
RE_MONEY = re.compile(
    u"[0-9][0-9\\.,]{0,12}?(?:万亿|亿|万)?(?:美元|欧元|克朗|日元|英镑|港元|元|卢布)|"
    u"[\\$¥￥][0-9]|[0-9][0-9\\., ]{0,10}?(?:billion|million|trillion)|"
    u"斥资|订单价值|价值约|总价值|合同价值|金额达", re.I)
# L2 订单/合同（须与装备共现，避免单独误判）
RE_ORDER = re.compile(
    u"receives order|signed a contract|获.{0,6}订单|签订.{0,6}合同|拿到.{0,6}订单|"
    u"订单|斥资|合同|contract|\\border\\b", re.I)
# 装备/代号（代号需过黑名单，不单独触发 L2）
RE_CODE = re.compile(
    u"导弹|护卫舰|驱逐舰|战机|雷达|鱼雷|武器系统|航母|潜艇|无人机|芯片|"
    u"frigate|fighter|warship|missile|radar|torpedo|submarine|carrier|drone|weapon|chip|"
    u"[A-Za-z]{1,6}[-]?[0-9]{1,3}[A-Za-z0-9]?", re.I)
CODE_BLACK = re.compile(u"G7|G20|G8|COVID|H5N|COVID-19|COVID19", re.I)
# L3 事件落点
RE_IMPACT = re.compile(
    u"军演|演习|联合宣言|宣言|联合声明|外长|选举|公投|法案|峰会|"
    u"drill|exercise|declaration|election|summit|referendum|ministers|statement", re.I)
# L6 观察/画像（明确体裁词；检方跨境追查/监视）
RE_WATCH = re.compile(
    u"密切关注|人物画像|态势综述|态势综合|关于.{2,10}研判|画像|长期跟踪|跨境监视|"
    u"检方.{0,6}(追查|监视|调查|追踪)|"
    u"profile|long-term|persona|a portrait of|"
    u"prosecutors.{0,24}(target|tracking|investigat|accused)", re.I)
# L1 已坐实安全化动作
RE_L1 = re.compile(
    u"威胁|袭击|攻击|破坏|骇入|黑客|爆炸|枪击|逮捕|禁令|禁止|封锁|断供|制裁|洗钱|走私|诈骗|"
    u"扣押|冻结|网络攻击|监控|渗透|窃密|军事|国防|国安|武器|导弹|围堵|遏制|"
    u"attack|strike|threat|hack|arrest|ban|sanction|missile|weapon|cyber|espionage|seize|seizure", re.I)


def _real_code(text):
    for m in RE_CODE.finditer(str(text or '')):
        if not CODE_BLACK.search(m.group(0)):
            return m.group(0)
    return ''


def route_style(r, blob=None):
    """分线只依据干净的 title + summary（不用 content，避免侧栏/引用语/相关推荐噪声）。
    顺序：网传→未坐实→客观个案→金额/订单装备→事件→观察画像→安全化动作→默认 L1。"""
    title = _simpl(r.get('title'))
    summ = _simpl(r.get('summary'))
    head = title + summ
    # L5 网传：标题命中，或 summary 有强视频爆料/流传标记（优先于标题弱词）
    if RE_NET.search(title) or RE_NET_STRONG.search(head):
        return "L5"
    # L4 未坐实：标题疑似/未证实，或匿名信源/备忘录式未坐实情报指控
    if not RE_CONFIRMED.search(title) and (
            RE_SUSPECT.search(title) or RE_UNVERIFIED_INTEL.search(head)):
        return "L4"
    # L7 客观个案（标题或 summary 强标记，优先于 L2）
    if RE_STATE.search(title) or RE_STATE.search(summ):
        return "L7"
    # L2 订单/合同/斥资（必须有订单信号），且含金额或装备
    if RE_ORDER.search(head) and (RE_MONEY.search(head) or RE_CODE.search(head)):
        return "L2"
    # L3 事件落点（标题）
    if RE_IMPACT.search(title):
        return "L3"
    # L6 观察/画像（标题或 summary）
    if RE_WATCH.search(title) or RE_WATCH.search(summ):
        return "L6"
    # L1 安全化动作（标题）
    if RE_L1.search(title):
        return "L1"
    return "L1"


# ================================================================ 标题规则表（分线，人工审过）
# 每条 (触发词全部命中, 候选标题)；命中后须过 title_ok_style 且核心词在正文。
TITLE_RULES = {
 "L1": [
   ((u"炸弹", u"威胁"), u"警惕欧洲航空业连环虚假炸弹威胁扰乱民航安全"),
   ((u"空壳", u"英伟达"), u"警惕英伟达先进芯片借空壳公司规避出口管制"),
   ((u"空壳", u"芯片"), u"警惕先进芯片借空壳公司规避出口管制"),
   ((u"德国", u"无人机"), u"警惕德国军方以安全风险为由禁用中国无人机"),
   ((u"古巴", u"制裁", u"首次"), u"警惕美对古巴制裁首次纳入中国企业"),
   ((u"伊朗", u"冷藏"), u"警惕伊朗借网络攻击波及海外连锁超市"),
   ((u"伊朗", u"超市"), u"警惕伊朗借网络攻击波及海外民生设施"),
   ((u"封锁", u"台湾", u"舰"), u"警惕解放军借大规模舰船集结模拟封锁台湾"),
   ((u"稀土", u"出口"), u"警惕美借稀土履约施压我放宽关键矿产出口"),
   ((u"稀土", u"履约"), u"警惕美借贸易谈判施压我履行稀土出口承诺"),
   ((u"调查", u"中止", u"芯片"), u"警惕美芯片调查在企业介入后中止留下监管缺口"),
   ((u"美光", u"暂停"), u"警惕美光暂停台湾芯片厂建设牵动半导体供应链"),
   ((u"烟草", u"资产"), u"警惕俄罗斯扣押日企资产冲击海外投资安全"),
   ((u"币安", u"被盗"), u"警惕加密货币交易所被盗凸显资金监管漏洞"),
   ((u"加密货币", u"不宜交易"), u"警惕加密货币交易所风险凸显虚拟资产监管漏洞"),
   ((u"滞留", u"芯片"), u"警惕大批英伟达芯片滞留香港凸显出口管制漏洞"),
   ((u"追踪", u"走私"), u"警惕英伟达加强芯片追踪应对东南亚走私链条"),
   ((u"关闭", u"代表处"), u"警惕驻外代表处遭打压关闭侵蚀外交空间"),
   ((u"代表处", u"打压"), u"警惕驻外机构遭定向打压侵蚀海外外交阵地"),
   ((u"空袭", u"原油"), u"警惕中东局势反复牵动能源价格与输入性风险"),
   ((u"贸易顺差", u"美元"), u"警惕巨额贸易顺差成为外部施压新借口"),
   ((u"知识产权", u"封锁"), u"警惕美借知识产权保护法封锁我在美投资实体"),
   ((u"影子舰队", u"假旗"), u"警惕伊朗影子舰队借假旗航行规避美制裁"),
   ((u"朝鲜", u"制裁"), u"警惕美借朝鲜制裁收紧数字货币跨境流转"),
   ((u"伊朗", u"数字货币"), u"警惕美借对伊制裁将数字货币中介列入制裁清单"),
   ((u"通用许可证",), u"警惕美调整对伊对俄制裁许可证留出规避空间"),
   ((u"网络", u"犯罪"), u"警惕美借网络犯罪列名扩大跨境人员管控范围"),
 ],
 "L2": [
   ((u"萨博", u"护卫舰"), u"萨博获20亿瑞典克朗护卫舰订单动向及涉我影响"),
   ((u"护卫舰", u"订单"), u"欧洲军工企业获大额护卫舰订单动向及涉我影响"),
   ((u"战斗机", u"订单"), u"欧洲军工企业获大额战机订单动向及涉我影响"),
 ],
 "L3": [
   ((u"G7", u"宣言"), u"G7外长联合宣言反对改变台海现状对我国影响分析"),
   ((u"七国集团", u"宣言"), u"七国集团外长联合宣言涉华对我国影响分析"),
   ((u"联合声明", u"台海"), u"外部势力联合声明涉台海对我国影响分析"),
   ((u"联合宣言", u"南海"), u"外部势力联合宣言涉南海对我国影响分析"),
 ],
 "L4": [
   ((u"黄仁勋",), u"疑似英伟达黄仁勋身边人员涉华情报活动"),
   ((u"空壳", u"企业"), u"疑似部分经手芯片企业为空壳规避出口管制"),
 ],
 "L5": [
   ((u"武装直升机", u"巡航导弹"), u"网传俄武装直升机发射新型巡航导弹信息待核实"),
   ((u"直升机", u"导弹"), u"网传俄直升机发射新型巡航导弹信息待核实"),
 ],
 "L6": [
   ((u"米兰", u"检察官"), u"密切关注米兰检方追查跨境监视海外异见者网络动态"),
   ((u"米兰", u"监视"), u"密切关注米兰检方追查跨境监视海外异见者网络动态"),
   ((u"米兰", u"检方"), u"密切关注米兰检方追查跨境监视海外异见者网络动态"),
   ((u"检方", u"跨境监视"), u"密切关注境外检方追查跨境监视网络动态"),
   ((u"检察官", u"异见"), u"密切关注境外检方追查跨境监视海外异见者网络动态"),
 ],
 "L7": [
   ((u"西北工业大学",), u"被美列入黑名单高校经第三方购得英伟达先进芯片"),
   ((u"黑名单", u"第三方"), u"被美列入黑名单机构经第三方购得先进芯片"),
   ((u"实体名单", u"购"), u"被美列入实体名单机构经第三方购得先进芯片"),
 ],
}

# 叠词拼凑（标题硬禁）
DUP_WORD = re.compile(u"([一-鿿]{2,4})\\1")
# 英文长串（短型号 H200/Mi-28 允许，整句英文禁止）
EN_LONG = re.compile(u"[A-Za-z]{4,}")
# 评论/分析体与网站弹窗噪声（事件标题硬禁；"凸显"为正常新闻词不在此列）
BAD_TITLE = re.compile(
    u"折射|示警|意味着|背后|恐怕|恐将|将更|加剧|透视|剖析|"
    u"请先同意|隐私政策|同意以下|cookie|立即注册|订阅|登录|注册以|了解更多")
# 标题半截结尾（结构助词/连词/介词/明显截断单字，正常完整标题不会以此收尾）
TITLE_BROKEN_END = re.compile(
    u"[的了攻在是和与及把被为以有个将对从到向于]$")
# 缺主体活动预告（"第X届…举行"、时间状语开头，未点明动作主体）
NO_SUBJECT = re.compile(
    u"第[一二三四五六七八九十0-9]+届.*举行$|^将于|^周[一二三四五六日]")


def title_ok_style(style, title):
    """分线标题校验；核心词在正文由调用方另判 title_in_body。"""
    t = str(title or '')
    zh = re.sub(u"[^一-鿿]", '', t)
    if len(zh) < 8 or DUP_WORD.search(t) or EN_LONG.search(t):
        return False
    if u"，" in t or u"," in t or u"、" in t:
        return False
    if re.search(u"是否|为何|如何|？|\\?|怎么|为什么|震惊|居然|社论|专栏|评论", t):
        return False
    if BAD_TITLE.search(t):
        return False
    if TITLE_BROKEN_END.search(t):
        return False
    if NO_SUBJECT.search(t):
        return False
    if style == "L1":
        return t.startswith(u"警惕") and 12 <= len(t) <= 40
    if style == "L2":
        return bool(re.search(u"\\d", t)) and len(t) <= 50
    if style == "L3":
        return bool(re.search(u"影响分析|风险分析|舆情分析", t))
    if style == "L4":
        return t.startswith(u"疑似")
    if style == "L5":
        return t.startswith(u"网传")
    if style == "L6":
        return bool(re.search(u"密切关注|研判|画像|动态", t))
    if style == "L7":
        return not re.match(u"^(警惕|疑似|网传)", t)
    return False


# 兜底标题：只从真实料的源标题/摘要提取具体事件短语，不做"国家+安全词"空泛模板
# 空泛词（兜底标题硬禁，杜绝"相关风险/高度警惕/值得跟踪"这类拼凑）
_GENERIC_P = re.compile(
    u"相关风险|相关情况|相关动向|相关问题|高度警惕|值得跟踪|值得研判|需高度|跟踪评估|持续跟踪|"
    u"隐私政策|请首先同意|文字转语音|同比|环比|出口创|创新高")
# 活动/会议预告（非安全事件，选句时排除）
_EVENT_NOTICE = re.compile(
    u"举行|举办|将于|召开|发布会|论坛|会议|开幕|出席|发表讲话|讲话|会展|纱厂|海报")
# 安全动作词（兜底优先选含这些词的句子，确保标题锚定真实安全动作）
_SEC_ACTION = re.compile(
    u"禁止|制裁|管制|封锁|攻击|黑客|间谍|情报|监控|监视|渗透|窃密|走私|洗钱|诈骗|"
    u"起诉|逮捕|扣押|冻结|断供|禁令|审查|胁迫|网络攻击|导弹|军演|演习|围堵|遏制|列名|罪名")
# 媒体引导语（提取主句时去除）
_LEAD_P = re.compile(
    u"^.{0,14}?(媒体|报道|消息|电视台|通讯社|报纸)[^，。；]{0,6}(称|报道|援引[^，。；]{0,10}称)?")
# 因果/时间从句（在这些词处截断，只留主句）
_CLAUSE_SPLIT = re.compile(u"因为|由于|此前|原因是|在被曝|事发于|背景是")


def _clean_phrase(s):
    """清洗单句：去括号/图注/英文片段/引导语/从句，保留干净中文主句。"""
    s = re.sub(u"（[^）]*）|\\([^)]*\\)", u"", s)
    s = re.sub(u"照片[：:][^。；]*|图片[：:][^。；]*|视频[：:][^。；]*", u"", s)
    s = re.sub(u"[A-Za-z]{2,}[^，。；]{0,30}", u"", s)
    s = re.sub(u"[“”\"\\s]", u"", s)
    s = _LEAD_P.sub(u"", s)
    s = re.sub(u"^(据称|据悉|据报|据介绍|据了解|据报道)", u"", s)
    s = _CLAUSE_SPLIT.split(s)[0]
    s = re.sub(u"[，。；、：:？！?]", u"", s)
    return s.strip()


def _extract_event(r):
    """收集源标题/摘要的中文候选句，过滤泛词与活动预告，优先返回含安全动作词的具体事件。"""
    cands = []
    t = _clean_phrase(_simpl(r.get('title')))
    if len(re.findall(u"[一-鿿]", t)) >= 8:
        cands.append(t)
    sm = _simpl(r.get('summary') or '')
    for s in re.split(u"[。；]", sm):
        c = _clean_phrase(s)
        if len(re.findall(u"[一-鿿]", c)) >= 10:
            cands.append(c)
    # 过滤空泛词与活动预告（时间地点/会议通知不是安全事件）
    valid = [c for c in cands if not _GENERIC_P.search(c) and not _EVENT_NOTICE.search(c)]
    if not valid:
        return u""
    sec = [c for c in valid if _SEC_ACTION.search(c)]
    return (sec or valid)[0]


# 自然断点（截断时优先在这些词处切，保留完整语义）
_BREAK_P = re.compile(u"且|并|同时|组织者|主办方|没有|呼吁|要求|此外|另外|其中|方面")


def _trim(s, maxlen):
    """超长时在自然断点处截断（不保留断点连接词），避免硬切产生半截词。"""
    if len(s) <= maxlen:
        return s
    best = 0
    for m in _BREAK_P.finditer(s):
        if m.start() <= maxlen:
            best = m.start()
        else:
            break
    out = s[:best] if best >= 10 else s[:maxlen]
    return re.sub(u"[且并的与和了及或，,、]$", u"", out)


def build_title_fallback(style, r, basics):
    """规则表未命中时的确定性兜底：提取真实事件短语，按线加前缀/后缀，过校验才返回。"""
    ev = _extract_event(r)
    if not ev:
        return u""
    prefix, suffix = u"", u""
    if style == "L1":
        prefix = u"警惕"
    elif style == "L4":
        prefix = u"疑似"
    elif style == "L5":
        prefix = u"网传"
    elif style == "L7":
        pass
    elif style == "L3":
        suffix = u"对我国影响分析"
    elif style == "L2":
        blob = _simpl((r.get('title') or '') + (r.get('summary') or ''))
        if not RE_MONEY.search(blob):
            return u""
        suffix = u"动向及涉我影响"
    else:
        return u""
    # 目标总长 28（精炼），按前缀/后缀反推事件短语可用长度并截断
    ev = _trim(ev, 28 - len(prefix) - len(suffix))
    cand = prefix + ev + suffix
    if not title_ok_style(style, cand):
        return u""
    if qc_body is not None and not qc_body.title_in_body(cand, basics):
        return u""
    return cand


def build_title_style(style, r, basics):
    """按线构造标题：规则表命中且校验通过、核心词在正文才返回；否则走确定性兜底。"""
    blob = _simpl((r.get('title') or '') + (r.get('summary') or '')
                  + (r.get('content') or '')[:2500])
    for triggers, title in TITLE_RULES.get(style, []):
        if all(w in blob for w in triggers):
            if title_ok_style(style, title) and (
                    qc_body is None or qc_body.title_in_body(title, basics)):
                return title
    return build_title_fallback(style, r, basics)


# ================================================================ 分线引言
INTRO_TAIL = {
    "L1": u"这是相关动向被安全化的新动作，需高度警惕、持续跟踪评估。",
    "L2": u"这是带明确资金和装备代号的系统性军工建设动作，对相关力量格局的影响需持续评估。",
    "L3": u"该动作对我周边安全环境的传导影响需前置评估、妥善应对。",
    "L4": u"相关迹象尚未经官方证实，需前置核实、密切关注，不轻易下结论。",
    "L5": u"相关网络信息需溯源核实、谨慎对待，不轻易转结论。",
    "L6": u"相关跨境动向需持续跟踪、动态研判。",
    "L7": u"这一事实折射相关管制的执行漏洞，需跟踪研判。",
}


# 半截句结尾标志（连词/助词/介词，正常完整句不会以此收尾）
_BROKEN_END = re.compile(u"[的了着和与及在把被为以，、；：]$")


def _quote_ok(s):
    """引号须左右配对；英文双引号须成对。"""
    if s.count(u'\u201c') != s.count(u'\u201d'):
        return False
    if s.count(u'\u2018') != s.count(u'\u2019'):
        return False
    if s.count('"') % 2 != 0:
        return False
    return True


# 点题句禁用：设问词、破折号/竖线侧栏拼接
_POINT_BAD = re.compile(
    u"是否|为何|如何|？|\\?|怎么|怎样|为什么|意味着|–|—|\\||外交官")
# 指代开头（点题句优先避开，避免"此举/这一"指代不明）
_PRONOUN_START = re.compile(u"^(此举|这一|该|其)")


def _clean_point(s):
    """点题句完整性：引号配对、非半截、无设问与侧栏拼接。"""
    return _quote_ok(s) and not _BROKEN_END.search(s) and not _POINT_BAD.search(s)


def build_intro_style(style, r, basics, media, dstr):
    """日期+据媒体报道+完整点题句（引号配对、非半截）+ 按线结尾判断。"""
    sents = [s.strip() for s in re.split(u"[。；]", basics)
             if 16 <= len(s.strip()) <= 70 and _clean_point(s.strip())]
    # 优先非指代开头的句子，避免"此举/这一"指代不明
    nonpro = [s for s in sents if not _PRONOUN_START.match(s)]
    if nonpro:
        point = nonpro[0]
    elif sents:
        point = sents[0]
    else:
        cands = [s.strip() for s in re.split(u"[。；]", basics) if _clean_point(s.strip())]
        point = cands[0][:60] if cands else u'相关动向值得关注'
    return u"%s据%s报道，%s。%s" % (dstr, media, point, INTRO_TAIL[style])


# ================================================================ 第 6 条主旨句（领域补第 6 条）
RISK_HEAD_EXTRA = {
    "军事安全": u"演训兵力外溢扩散，区域军备竞赛加剧",
    "经济安全": u"外溢效应持续发酵，长期发展环境承压",
    "科技安全": u"技术封锁长期化，创新生态面临挤压",
    "社会安全": u"安全焦虑蔓延扩散，社会心理预期承压",
    "网络安全": u"网络威胁跨界传导，整体安全防线承压",
    "金融安全": u"风险跨市场传染，金融稳定预期承压",
    "文化安全": u"渗透圈层加速扩散，主流舆论阵地承压",
    "政治安全": u"苗头隐患累积发酵，系统风险防控承压",
}
ADVICE_HEAD_EXTRA = {
    "军事安全": u"深化军事外交互动，构建危机管控机制",
    "经济安全": u"加强国际经贸协调，营造稳定外部环境",
    "科技安全": u"完善创新体制机制，激活内生发展动力",
    "社会安全": u"做实民生保障基础，筑牢社会稳定根基",
    "网络安全": u"健全协同治理体系，提升整体防护效能",
    "金融安全": u"完善风险防控体系，守住金融安全底线",
    "文化安全": u"厚植文化自信根基，增强国家认同凝聚",
    "政治安全": u"强化系统治理能力，筑牢国家安全防线",
}
ADVICE_BODY_EXTRA = {
    "军事安全": u"由外事和军队外联部门牵头，建立海上相遇规则、军事热线和危机沟通机制，规范一线相遇处置，减少误判擦枪，推动安全对话与信任措施建设。",
    "经济安全": u"由商务和外事部门牵头，加强多双边经贸磋商和政策协调，主动参与规则制定，反对单边保护主义，为企业营造稳定、可预期的外部发展环境。",
    "科技安全": u"由科技和体制改革部门牵头，完善科研评价、成果转化和人才激励机制，优化创新资源配置，营造宽容失败、鼓励原创的良好生态，激活内生动力。",
    "社会安全": u"由民政和相关部门牵头，健全社会保障、就业支持和社会心理服务体系，夯实基层治理和民生基础，及时疏导矛盾，从源头筑牢社会稳定根基。",
    "网络安全": u"由网信部门牵头建立跨部门、跨区域联防联控，统筹监测、预警、处置和追责，推动数据共享与协同演练，提升网络安全整体防护效能。",
    "金融安全": u"由金融管理部门牵头，健全跨市场、跨业态风险监测预警和处置机制，强化宏观审慎管理，压实机构责任，牢牢守住不发生系统性风险底线。",
    "文化安全": u"由宣传和教育部门牵头，加强优秀文化建设和爱国主义教育，培育践行主流价值，增强文化认同和凝聚力，提升公众文化辨别与免疫能力。",
    "政治安全": u"由国家安全统筹机构牵头，坚持系统观念统筹发展和安全，完善风险研判、防控协同和责任落实机制，推动关口前移，筑牢国家安全人民防线。",
}


def risk_heads_6(domain, base_heads):
    return list(base_heads) + [RISK_HEAD_EXTRA.get(domain, RISK_HEAD_EXTRA["政治安全"])]


def advice_heads_6(domain, base_heads):
    return list(base_heads) + [ADVICE_HEAD_EXTRA.get(domain, ADVICE_HEAD_EXTRA["政治安全"])]
