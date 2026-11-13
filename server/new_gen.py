# -*- coding: utf-8 -*-
"""
new_gen.py —— 干净的确定性生成器（纯代码：正则/查表/可校验/可改，不依赖模型）
与旧 build_json 模板系统并行：
  正文(basics)  = 原文事实句直抄，天然过 final_clean 8-gram 核对
  标题(title)   = 源标题清洗，必须过 title_ok 且 title_in_body，否则放弃该料
  引言(intro)   = 严格模板「YYYY年M月D日，据<媒体>报道」+ 原文点题句，不混入任何噪声
  风险(risks)   = 领域对仗主旨句 + 原文直抄句(强制锚点)，条数服从事实
  对策(advices) = 领域动宾主旨句 + 确定性"部门+抓手+效果"（建议非事实，可模板）
"""
import re
import sys
import json
import sqlite3
import datetime

sys.path.insert(0, '/opt/intelhub/deliver')
import qc_body
import gen_deliver as gd
import auto_gen as ag
import flow_rules as fr
import seven_line as sl

# ---------------------------------------------------------------- 媒体名清洗
# 标准媒体名映射（处理英文/缩写/带栏目后缀的 source）
_MEDIA_MAP = [
    (re.compile(r'BBC|英国广播'), 'BBC'),
    (re.compile(r'美联社|AP\b|Associated'), '美联社'),
    (re.compile(r'路透|Reuters'), '路透社'),
    (re.compile(r'彭博|Bloomberg'), '彭博社'),
    (re.compile(r'金融时报|Financial Times'), '金融时报'),
    (re.compile(r'华尔街日报|Wall Street'), '华尔街日报'),
    (re.compile(r'纽约时报|New York Times'), '纽约时报'),
    (re.compile(r'日经|Nikkei'), '日经新闻'),
    (re.compile(r'共同社'), '共同社'),
    (re.compile(r'韩联社|Yonhap'), '韩联社'),
    (re.compile(r'法新社|AFP'), '法新社'),
    (re.compile(r'美国之音|VOA'), '美国之音'),
    (re.compile(r'德国之声|Deutsche Welle|DW'), '德国之声'),
    (re.compile(r'外交学者|Diplomat'), '外交学者杂志'),
    (re.compile(r'马尼拉时报'), '马尼拉时报'),
    (re.compile(r'联合报'), '联合报'),
    (re.compile(r'南华早报|South China'), '南华早报'),
    (re.compile(r'联合早报'), '联合早报'),
    (re.compile(r'香港自由新闻|HKFP|Hong Kong Free'), '香港自由新闻'),
]
# 栏目/导航垃圾词（媒体名里要剥掉）
_MEDIA_JUNK = ("国际纵览", "中国聚焦", "深度观察", "滚动新闻", "即时新闻", "要闻速递",
               "首页推荐", "热点追踪", "独家报道", "专题报道", "环球视线", "中文网",
               "中文版", "国际频道", "新闻频道")


def clean_source(src):
    """返回干净媒体名；优先用映射表，否则取分隔符前的中文主体。"""
    s = str(src or '').strip()
    for rx, std in _MEDIA_MAP:
        if rx.search(s):
            return std
    # 取分隔符前主体
    for sep in ('｜', '|', '—', '–', '-', '·', '：', ':'):
        if sep in s:
            s = s.split(sep)[0].strip()
    for w in _MEDIA_JUNK:
        s = s.replace(w, '')
    # 只保留中文核心（去掉英文/数字/空白），兜底
    zh = re.sub(r'[^一-鿿]', '', s)
    zh = zh.strip('，,。.；;')
    return zh[:12] if zh else '境外媒体'


# ---------------------------------------------------------------- 标题（源标题清洗）
# ---------------------------------------------------------------- 安全题材准入（硬门）
# 非安全题材强信号（简体，判断前先转简体）
_NON_SPORT = re.compile(u"棒球|篮球|足球|球员|球队|球赛|联赛|赛事|比赛|赛季|冠军|亚运|奥运|世界杯|"
                        u"锦标赛|全垒打|投手|中继|先发|打者|入札|大联盟|泳渡|路跑|马拉松|球场|球星|"
                        u"教练|战绩|季后赛|选手|田径|网球|羽球|排球|击球|球棒|盗垒|赛|棒")
_NON_SHOW = re.compile(u"艺人|明星|综艺|偶像|演员|歌手|演唱会|网红|剧集|影视|八卦|粉丝|代言|颁奖|"
                       u"金马|金钟|偶像剧|主持人|节目|艺人|出道|专辑")
_NON_LIFE = re.compile(u"小吃|美食|餐厅|护心|三高|血压|血糖|养生|景点|旅游|观光|导览|星空|认证|"
                       u"特产|石斑|养殖|渔民|农户|气温|天气|商圈|嘉年华|园游会|风景|露营|民宿|饭店|"
                       u"百货|促销|优惠|灯会|花季|健康|饮食|营养|食谱|餐|饮|玩|游|客|美食")
_NON_LOCAL = re.compile(u"市长|议员|里长|候选人|选民|选举|罢免|造势|辅选|参选|问政|质询|党部|绿营|"
                        u"蓝营|政见|拜票|投票|公所|生日|发文|怒批|反击|告|提告|报案|判赔|求偿")
# 安全正向信号（标题必须命中至少一个）
_SEC_TITLE = re.compile(u"制裁|管制|禁运|出口|断供|渗透|策反|情报|间谍|窃密|军演|演习|巡航|抵近|军事|"
                        u"洗钱|走私|诈骗|引渡|起诉|清单|封锁|网络攻击|认知战|舆论战|涉华|对华|反华|"
                        u"台独|藏独|疆独|港独|分裂|颠覆|跨境|洗白|灰色|军方|国防|国安|监控|侦察|武器|"
                        u"导弹|核|芯片|半导体|关键矿产|稀土|网络|太空|卫星|海底|关税|围堵|遏制|安全化|"
                        u"情报机构|武装|部队|海军|空军|雷达|潜艇|无人机|量子|数据安全|供应链|禁令")


# 时政缩略模式：双字紧接"会/会前"或"协议"（高度概括的高层时政缩略，不自动成稿）
_LEADER_HUI = re.compile(u"[\u4e00-\u9fa5]{2}(?:会|会前)")
_LEADER_XIEYI = re.compile(u"[\u4e00-\u9fa5]{2}协议")
# 正常含"会"的词，排除，避免误杀
_SAFE_HUI = (u"博览", u"交易", u"促进", u"董事", u"委员", u"理事", u"参议", u"联合",
             u"国际", u"世界", u"座谈", u"研讨", u"展览", u"展销", u"招聘", u"动员",
             u"报告", u"峰会", u"集会", u"聚会", u"大会", u"社会", u"机会", u"参议",
             u"奥运", u"亚运", u"颁奖", u"董事", u"理事", u"股东", u"监事")
# 正常"XX协议"前缀，保护合规协议
_SAFE_XIEYI = (u"合作", u"框架", u"贸易", u"投资", u"收购", u"和平", u"停战", u"撤军",
               u"停火", u"双边", u"多边", u"经贸", u"签署", u"战略", u"安全", u"防务",
               u"军事", u"联盟", u"伙伴", u"引渡")
# 高层人事/权斗/清洗类：敏感且多为大众已知，不自动成稿
_ELITE_PURGE = re.compile(u"落马|出事|清洗|红二代|政变|逼宫|夺权|倒台|下台|被查|双规|权斗|"
                          u"大老虎|老虎|揭.*泄密|反对.*攻台|政变|兵变|废黜|软禁")

# 隐私八卦/情色丑闻类：个人隐私角度不是国安研判（黄仁勋婚外情系列等），整类拦
_GOSSIP = re.compile(u"婚外情|婚外|出轨|外遇|不伦|桃色|丑闻|情妇|情人|亲密关系|聚光灯|"
                     u"外遇对象|承认.{0,3}道歉|绯闻|情史")
# 栏目/媒体名/历史回顾/股市行情/纯商业类：出现在标题即拦（非研判事件）
_GARBAGE_TITLE = re.compile(u"历史上的今天|歷史上的今天|要闻解说|一文看懂|法国世界报|日经中文网|"
                            u"股市|收盘|收盤|暴跌|财报|財報|参展|參展|新品|股价|股價|指数|指數|"
                            u"中文版|日本经济新闻中文版|栏目|专栏")
# 公开宣判/已进入司法程序热点：官方已公开、媒体充分报道、大众已知，不属隐蔽前瞻
_PUBLIC_VERDICT = re.compile(u"加判|重判|宣判|判刑|监禁|求刑|出狱|出獄|刑期|遭判|被判[\u4e00-\u9fa5]{0,3}年")
# 网页功能/隐私噪声（采集残留，整类拦）
_WEB_NOISE = re.compile(
    u"隐私政策|请首先同意|请先同意|激活文字转语音|文字转语音|使用条款|点击订阅|订阅我们|"
    u"请启用|浏览器不支持|Cookie政策|继续浏览即表示")
# 纯经济数据/行情（非安全研判事件）
_ECON_DATA = re.compile(
    u"出口创|进出口|同比增长|同比增|环比|创历史新高|创新高|外贸数据|经济成长|景气对策|"
    u"出口.{0,3}(增长|猛增|攀升|创高)|增长近|猛增近")
# 涉我领导人的外媒报道（不自动成稿，避免敏感与误读）
_LEADER_CN = re.compile(u"习近平|李强|王沪宁|赵乐际|蔡奇|丁薛祥")


def security_admit(r):
    """硬门：只有真安全题材才放行。返回 (ok, 原因)。标题是事件主旨，重点看标题。"""
    title = fr.to_simplified(r.get('title') or '')
    body = fr.to_simplified((r.get('summary') or '') + (r.get('content') or '')[:1500])
    if not title:
        return False, u'无标题'
    # 信源信誉：必须在白名单（复用 gen_deliver 口径，拦大纪元/看中国等边缘媒体）
    if not gd._SRC_OK.search(str(r.get('source') or '')):
        return False, u'信源不在白名单'
    # 网页功能/隐私噪声（采集残留）
    if _WEB_NOISE.search(title) or _WEB_NOISE.search(body[:900]):
        return False, u'网页功能/隐私噪声'
    # 涉我领导人的外媒报道不自动成稿
    if _LEADER_CN.search(title) or _LEADER_CN.search(body[:600]):
        return False, u'涉领导人题材'
    # 人名+观点动词+冒号，或空格/分隔后短人名直接+冒号（时政观点表态，非研判事件）
    if re.search(u"[\u4e00-\u9fa5]{2,4}(?:示警|认为|表示|指出|呼吁|强调|警告|提醒)[:：]", title) \
            or re.search(u"(?:^|[\s|])[\u4e00-\u9fa5]{2,4}[:：]", title):
        return False, u'观点表态标题'
    # 纯经济数据/行情
    if _ECON_DATA.search(title):
        return False, u'经济数据题材'
    # 作者专栏前缀（2-4字中文+冒号开头）：评论专栏不是新闻
    if re.match(u'[\u4e00-\u9fa5]{2,4}[:：]', title):
        return False, u'作者专栏题材'
    # 隐私八卦/情色丑闻类：个人隐私角度不进研判
    if _GOSSIP.search(title):
        return False, u'隐私八卦题材'
    # 栏目/媒体名/历史回顾/股市行情/纯商业类：非研判事件
    if _GARBAGE_TITLE.search(title):
        return False, u'栏目/股市/商业非研判题材'
    # 公开宣判热点：大众已知，不属隐蔽前瞻
    if _PUBLIC_VERDICT.search(title):
        return False, u'公开宣判热点题材'
    # 检查所有"XX会/会前"匹配，任一不在安全词即拦
    for _m in _LEADER_HUI.finditer(title):
        if not any(w in _m.group(0) for w in _SAFE_HUI):
            return False, u'时政缩略题材'
    # 检查所有"XX协议"匹配，前缀不在白名单即拦
    for _m in _LEADER_XIEYI.finditer(title):
        if not any(w in _m.group(0) for w in _SAFE_XIEYI):
            return False, u'时政缩略题材'
    # 高层人事/权斗/清洗类
    if _ELITE_PURGE.search(title):
        return False, u'高层人事题材'
    # 标题含体育/娱乐强信号 → 直接拒
    if _NON_SPORT.search(title) or _NON_SHOW.search(title):
        return False, u'标题体育/娱乐题材'
    # 正文安全/非安全信号计数（提前算，供标题兜底用）
    non = (len(_NON_SPORT.findall(body)) + len(_NON_SHOW.findall(body))
           + len(_NON_LIFE.findall(body)) + len(_NON_LOCAL.findall(body)))
    sec = len(_SEC_TITLE.findall(body))
    # 标题不含安全词：民生/地方直接拒；gov_action 官方链路由采集器保证题材；否则看正文是否安全题材主导
    if not _SEC_TITLE.search(title):
        if str(r.get('route') or '') == 'gov_action':
            pass  # OFAC/BIS 确定性官方动作，标题为机翻，题材与可溯源性由采集器保证
        elif _NON_LIFE.search(title) or _NON_LOCAL.search(title):
            return False, u'标题民生/地方题材'
        elif sec >= 4 and non <= sec:
            pass  # 标题中性但正文安全主导，放行
        else:
            return False, u'标题无安全信号'
    # 正文非安全信号压倒性占多 → 拒（gov_action 官方链路由采集器保证题材，不做此词频判断）
    if str(r.get('route') or '') != 'gov_action' and non > sec * 2 and sec < 3:
        return False, u'正文非安全题材主导'
    return True, u'ok'


# 设问/评论体标志：标题里出现即弃用（不是研判句式）
_QUESTION_WORDS = (u"是否", u"为何", u"如何", u"能不能", u"会不会", u"能不能", u"意味着",
                   u"？", u"?", u"怎么", u"怎样", u"为什么", u"何以为", u"何以", u"难不难")


# 栏目名/评论体/小报词：标题里出现即弃用（不是研判句式）
_COLUMN_WORDS = (u"黑白集", u"今日焦点", u"观察站", u"新闻透视", u"透视", u"社论", u"专栏",
                 u"评论", u"时评", u"短评", u"快评", u"专论", u"论坛", u"焦点", u"热点",
                 u"话题", u"纵深", u"前线", u"观点", u"报报", u"看版", u"专题", u"焦点评论")
_TABLOID_WORDS = (u"惨", u"震惊", u"居然", u"竟然", u"傻眼", u"崩了", u"翻车", u"怒了",
                  u"炸锅", u"劲爆", u"爆雷", u"囧", u"雷", u"吓尿", u"惊呆")
# 媒体名（出现在标题里要剥掉）
_MEDIA_TAIL = re.compile(u"(华尔街日报|纽约时报|华盛顿邮报|金融时报|联合报|中国时报|自由时报|"
                         u"路透社|彭博社|日经新闻|BBC|卫报|外交学者|政客杂志|政客)$")
# 标题主体内部出现媒体名（不在末尾也要拦）
_MEDIA_NAME_INSIDE = re.compile(u"华尔街日报|纽约时报|华盛顿邮报|金融时报|联合报|中国时报|"
                                u"自由时报|路透社|彭博社|日经新闻|卫报|政客")


def clean_src_title(src):
    """源标题清洗成纯中文（简体）警惕式；过 title_ok 且无栏目/设问/小报/媒体尾巴，否则空串。"""
    t = fr.to_simplified(str(src or ''))
    t = qc_body._Q.sub('', t)
    t = re.sub(u"据[^，。]{2,12}报道", "", t)
    t = re.sub(u"（[^）]*）|\([^)]*\)", "", t)
    t = re.sub(u"[A-Za-z][A-Za-z0-9 .,%’'-]*", "", t)
    t = t.replace(u"据报", "").replace(u"据悉", "").replace(u"据称", "")
    t = _MEDIA_TAIL.sub("", t)
    out = []
    for x in re.split(u"[，,、。；;:：]+", t):
        x = re.sub(u"[^一-鿿]", "", x)
        x = _MEDIA_TAIL.sub("", x)
        if len(x) < 10:
            continue
        # 标题主体里不得含媒体名/栏目词
        if any(w in x for w in _QUESTION_WORDS + _COLUMN_WORDS + _TABLOID_WORDS):
            continue
        if _MEDIA_NAME_INSIDE.search(x):
            continue
        c = ("警惕" + x)[:40]
        if qc_body.title_ok(c) and not c.startswith(u"警惕他") and not c.startswith(u"警惕她"):
            out.append(c)
    return out[0] if out else ""


# ---------------------------------------------------------------- 事件规则式标题（构造，非清洗）
# 每条规则：(触发词组[须全部命中], 候选标题)；标题须过 title_ok 且核心词在正文，否则放弃该料
_TITLE_RULES = [
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
    # —— OFAC/BIS 官方动作确定性链路（触发词均取自机翻正文实际用词）——
    ((u"知识产权", u"封锁"), u"警惕美借知识产权保护法封锁我在美投资实体"),
    ((u"影子舰队", u"假旗"), u"警惕伊朗影子舰队借假旗航行规避美制裁"),
    ((u"朝鲜", u"制裁"), u"警惕美借朝鲜制裁收紧数字货币跨境流转"),
    ((u"伊朗", u"数字货币"), u"警惕美借对伊制裁将数字货币中介列入制裁清单"),
    ((u"通用许可证",), u"警惕美调整对伊对俄制裁许可证留出规避空间"),
    ((u"网络", u"犯罪"), u"警惕美借网络犯罪列名扩大跨境人员管控范围"),
]


def build_title(r, cands, basics):
    """按事件规则构造规范研判标题；触发且标题核心词在正文、过 title_ok 才返回，否则空串。"""
    blob = fr.to_simplified(
        (r.get('title') or '') + (r.get('summary') or '') + (r.get('content') or '')[:2500])
    for triggers, title in _TITLE_RULES:
        if all(w in blob for w in triggers):
            if qc_body.title_ok(title) and qc_body.title_in_body(title, basics):
                return title
    return ""


# ---------------------------------------------------------------- 正文硬伤过滤（11-13 加固）
# 图注/配图说明句：不是正文事实（截图实锤"资料照片：民众在台北…"混入基本情况）
_CAPTION = re.compile(
    u"资料照片|资料图片|图片说明|图片来源|配图|摄于|供图|本图|示意图|"
    u"（[^）]*摄）|\\([^)]*摄\\)|(?:^|[\\s，])图[：:]|^照片")
# 旧时间节点：明确旧年份（2010-2025）或"星期X(月X日)"相对日期，基本情况只写最新、不翻旧账
_OLD_YEAR = re.compile(u"20(?:1[0-9]|2[0-5])年")
_WEEK_PAREN = re.compile(u"星期[一二三四五六日][\\(（]")
# gov_action 归纳稿专用噪声：从通用噪声中去掉"注册"（"登记注册号被点名"是有效事实）
_SDN_NOISE = re.compile(
    u"责任编辑|版权所有|Copyright|©|扫码|订阅|登录|隐私政策|cookie|Cookie|"
    u"点击|阅读原文|相关阅读|热门推荐|广告|转载|实习编辑|校对|我们认为|我觉得")
# 连续标点/空括号等清洗噪声
_BAD_PUNCT = re.compile(u"，，|、，|，。|，、|（）|\\(\\)|【】|\\[\\]|。\\s*。|，\\s*，")
# 剥英文后句首残缺标志（英文公司名被整删，留下"的波斯伍德工厂"等）
_BROKEN_START = re.compile(u"^[的了着和与及，、。；：]")
# 残缺在句中：逗号后直接跟"的+名词"（英文公司名被删，"协议，的工厂"），正常中文不出现"，的"
_BROKEN_MID = re.compile(u"，的")


def _zh_only(s):
    return re.sub(u"[^一-鿿]", "", s)


def _bg_set(s):
    z = _zh_only(s)
    return set(z[i:i + 2] for i in range(max(0, len(z) - 1)))


def _is_dup_sent(s, out):
    """跨句去重：子串包含，或 bigram Jaccard 高度重叠（拦大段重复/换序重复）。"""
    z = _zh_only(s)
    bg = _bg_set(s)
    for p in out:
        pz = _zh_only(p)
        if z and (z in pz or pz in z):
            return True
        pb = _bg_set(p)
        if bg and pb and len(bg & pb) / len(bg | pb) > 0.62:
            return True
    return False


def _sdn_name_key(s):
    """归纳条目名：去破折号后取第一个逗号/顿号前的主体名。"""
    t = s.lstrip(u"——").strip()
    return re.split(u"，|、", t, 1)[0]


def _is_dup_sdn(s, out):
    """名单归纳去重：仅当条目主体名相同才判重，对仗句式的不同对象一律保留。"""
    key = _sdn_name_key(s)
    return bool(key) and any(_sdn_name_key(p) == key for p in out)


def strip_english(s):
    """9·21 新规：正文纯中文，剥括号内英文原名及零散英文单词。"""
    s = re.sub(u"（[^）]*[A-Za-z][^）]*）", "", s)
    s = re.sub(r"\([^)]*[A-Za-z][^)]*\)", "", s)
    s = re.sub(r"[A-Za-z][A-Za-z0-9 .,'&’-]*", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    # 中文/数字之间不保留英文剥除后残留的孤立空格（"1840 万"→"1840万"、"返回 与"→"返回与"）
    s = re.sub(r"(?<=[一-鿿0-9])\s+(?=[一-鿿0-9])", "", s)
    s = s.strip()
    return s


def clean_sent(s):
    """清理直抄句：去英文、去句首/句尾引号、空白、括号残片。"""
    s = str(s).strip()
    s = strip_english(s)
    s = re.sub(u'^[“”‘’「」"\'\\s]+', '', s)
    s = re.sub(u'[“”‘’「」"\'\\s]+$', '', s)
    # 去掉句首孤立的引号后残留
    s = s.strip()
    return s


# ---------------------------------------------------------------- 原文事实句直抄（补 basics）
def _candidate_sents(r):
    """收集原文中合规、有出处、含实体的候选直抄句（保持原文顺序）。"""
    content = qc_body.scrub_page(r.get('content') or '')
    summary = qc_body.scrub_page(r.get('summary') or '')
    ref = content + ' ' + str(r.get('title') or '') + ' ' + summary
    G = qc_body._grams(ref, 8)
    src = content + '。' + summary
    out = []
    _is_gov = str(r.get('route') or '') == 'gov_action'
    for s0 in re.split(u'[。；！？\n]', src):
        s = s0.strip()
        if not (12 <= len(s) <= 180):
            continue
        # 竖线分隔的是标签/面包屑导航，不是正文句子
        if u'|' in s or u'｜' in s:
            continue
        # 图注/配图说明句、坏标点噪声：直接剔除
        if _CAPTION.search(s) or _WEEK_PAREN.search(s):
            continue
        # gov_action 归纳稿：成立日期是有效事实，跳过旧年份；其余题材拦旧时间
        if not _is_gov and _OLD_YEAR.search(s):
            continue
        if _BAD_PUNCT.search(s):
            continue
        # gov_action 用专用噪声（不含"注册"），框架/依据句不强制实体；其余题材用通用噪声+实体门
        if _is_gov:
            if _SDN_NOISE.search(s):
                continue
        elif qc_body._SKEL_NOISE.search(s) or not qc_body._SKEL_ENT.search(s):
            continue
        # gov_action 为 OFAC/BIS 官方确定性链路，含真实英文实体名/地址/法条，
        # 放宽中文占比；条目行（——开头）名称可能为英文，进一步放宽；其余题材维持 0.6
        if _is_gov:
            _min_zh = 0.2 if s.startswith(u'——') else 0.35
        else:
            _min_zh = 0.6
        if qc_body.zh_ratio(s) < _min_zh:
            continue
        if not (qc_body._grams(s, 8) & G):
            continue
        s = clean_sent(s)
        if len(s) < 12:
            continue
        # 剥英文致句首/句中残缺、跨句重复：清洗后判定
        if _BROKEN_START.search(s) or _BROKEN_MID.search(s):
            continue
        # 名单归纳按条目主体名去重，其余题材按整句相似度去重
        if (_is_dup_sdn if _is_gov else _is_dup_sent)(s, out):
            continue
        out.append(s)
    return out


def _join_sents(picked):
    """拼接句子，去除相邻句首尾重复词（如 台灣。台灣主要 → 台灣主要）。"""
    out = []
    for s in picked:
        if out:
            prev = out[-1]
            for L in (4, 3, 2):
                if len(prev) >= L and len(s) >= L and prev[-L:] == s[:L]:
                    s = s[L:]
                    break
        out.append(s)
    return ''.join(x + '。' for x in out)


def build_basics(cands, target, anchor_min, org_re, num_re):
    """从候选池直抄事实句拼 basics，按字数+锚点达标终止；返回(basics, 锚点数, 已用句list)。"""
    def is_anchor(s):
        return bool(org_re.search(s) or num_re.search(s))

    strong = [s for s in cands if is_anchor(s)]
    weak = [s for s in cands if not is_anchor(s)]
    picked, han, anchors = [], 0, set()
    for s in strong + weak:
        picked.append(s)
        han += len(qc_body._HAN.findall(s))
        for m in org_re.findall(s):
            anchors.add('o' + str(m))
        for m in num_re.findall(s):
            anchors.add('n' + str(m))
        if han >= target and len(anchors) >= anchor_min and len(picked) >= 4:
            break
    return _join_sents(picked), len(anchors), picked


# ---------------------------------------------------------------- 风险：主旨句 + 原文直抄（强制锚点）
def _kw_from_head(head):
    """从对仗主旨句提取核心名词关键词（2-4字）。"""
    # 去掉前后两段的动词性开头，取含实义的名词片段
    kws = re.findall(u'[一-鿿]{2,4}', head)
    stop = (u"风险", u"压力", u"隐患", u"受冲", u"承压", u"上升", u"加剧", u"加大",
            u"受迫", u"受限", u"失守", u"受牵", u"受冲", u"抬升", u"受损")
    out = []
    for k in kws:
        if not any(w in k for w in stop):
            out.append(k)
    return out[:4]


def build_risks(domain, cands, basics_used, org_re, num_re):
    """每条风险：同领域主旨句 + 含锚点的原文事实句。
    同领域保证不跨领域串台；按主旨关键词→领域词→任意锚点→复用basics 顺序匹配，
    每个事实句只用一次；条数服从事实。"""
    _base_heads = ag.DOMAIN_RISK_HEADS.get(domain, ag.DOMAIN_RISK_HEADS["政治安全"])
    heads = sl.risk_heads_6(domain, _base_heads)
    dom_words = ag._BODY_DOM_POOLS.get(domain, set())
    anchor_all = [s for s in cands if org_re.search(s) or num_re.search(s)]
    risks = []
    used = set()
    for head in heads:
        kws = _kw_from_head(head)
        match = None
        # 1. 含主旨关键词的锚点句
        for s in anchor_all:
            if s in used:
                continue
            if kws and any(k in s for k in kws):
                match = s
                break
        # 2. 含领域词的锚点句
        if match is None:
            for s in anchor_all:
                if s in used:
                    continue
                if any(w in s for w in dom_words):
                    match = s
                    break
        # 3. 任意未用锚点句
        if match is None:
            for s in anchor_all:
                if s not in used:
                    match = s
                    break
        # 4. 复用基本情况里的锚点句
        if match is None:
            for s in basics_used:
                if s not in used and (org_re.search(s) or num_re.search(s)):
                    match = s
                    break
        if match is None:
            continue
        used.add(match)
        body = match + '。' + _risk_logic(domain, head)
        risks.append([head, body])
    return risks


def _risk_logic(domain, head):
    """确定性逻辑分析句（不新增具体事实，只做传导判断），贴主旨句。"""
    table = {
        "军事安全": u"相关动作针对性、指向性明显，若持续推进将抬升周边摩擦概率，需前置防范。",
        "经济安全": u"壁垒一旦成型易被援引复制，相关产业和出口订单面临连带冲击。",
        "科技安全": u"管制手段具示范效应，可能沿产业链向相邻环节传导，挤压我企业空间。",
        "社会安全": u"手法若固化为可复制模式，受害群体和外溢风险将进一步扩大。",
        "网络安全": u"攻击工具和路径可被复用，关键信息基础设施防护压力持续存在。",
        "金融安全": u"资金通道若被打通或切断，都将对跨境结算和监管形成连锁影响。",
        "文化安全": u"软性渗透潜移默化，长期累积将侵蚀价值认同和舆论防线。",
        "政治安全": u"苗头阶段若失管，组织、资金、人员衔接可能转入更深盲区，事后处置成本倍增。",
    }
    return table.get(domain, table["政治安全"])


# ---------------------------------------------------------------- 对策：主旨句 + 确定性模板
_ADVICE_BODY = {
    "军事安全": [
        u"由军队和国家安全机关牵头，常态化摸排周边兵力部署与演训动向，建立分级预警和应急响应预案，确保异常动向早发现、早处置。",
        u"由国防动员部门牵头，补齐备战打仗短板，针对性提升联合作战和慑战止战能力，形成有效制衡。",
        u"由国家安全机关牵头，强化重点方向反渗透反窃密工作，严密防范情报搜集和人员策反。",
        u"由外事和法务部门牵头，运用外交和法理渠道揭批外部军事勾连，争取国际理解支持。",
        u"由宣传部门牵头，加强舆论引导，及时澄清虚假叙事，防范军事议题被恶意炒作。",
    ],
    "经济安全": [
        u"由商务部门牵头，跟踪主要经济体经贸政策和管制动向，健全外贸风险预警和企业帮扶机制。",
        u"由商务和贸促部门牵头，开拓东盟、中东、拉美等多元市场，降低对单一市场依赖。",
        u"由发改和工信部门牵头，推动产业链升级和关键环节攻关，提升应对壁垒的内生能力。",
        u"由法务和商务部门牵头，善用多边争端解决机制，支持企业依法应诉、维护权益。",
        u"由发改和自然资源部门牵头，夯实关键资源储备和循环利用，增强产业链供应链韧性。",
    ],
    "科技安全": [
        u"由科技和国家安全部门牵头，建立科技安全风险监测预警，动态评估管制和清单影响。",
        u"由网信部门牵头，严管数据跨境流动，落实数据出境安全评估，守牢数据安全底线。",
        u"由科技和教育部门牵头，审查涉外学术合作与交流，防范技术情报被违规搜集。",
        u"由工信部门牵头，集中攻关芯片、工业软件、核心算法等关键技术，推进自主可控。",
        u"由市场监管和标准化部门牵头，主动参与国际标准制定，争取规则和标准话语权。",
    ],
    "社会安全": [
        u"由公安和国家安全机关牵头，摸清跨境犯罪链条，强化情报研判和专案打击。",
        u"由公安和金融监管部门牵头，紧盯涉案资金流向，切断资产境外洗白通道。",
        u"由外事和领事部门牵头，加强出境风险提示和海外领事保护，保障公民安全。",
        u"由公安部门牵头，深化国际执法合作，联手打击跨境诈骗和非法拘禁。",
        u"由网信部门牵头，压实网络平台责任，斩断虚假招募和引流信息传播。",
    ],
    "网络安全": [
        u"由网信和公安部门牵头，强化关键信息基础设施防护，提升监测预警和攻防能力。",
        u"由网信部门牵头，严管数据跨境流动，打击违规采集和泄露个人信息行为。",
        u"由工信和网信部门牵头，排查供应链安全漏洞，清除预置后门和隐患。",
        u"由公安和网信部门牵头，整治非法翻墙和加密通信工具，封堵有害信息通道。",
        u"由网信部门牵头，治理网络水军和虚假账号，净化网络舆论环境。",
    ],
    "金融安全": [
        u"由人民银行和外汇管理部门牵头，强化跨境资金监测，精准锁定异常流动。",
        u"由金融监管和公安部门牵头，严打虚拟货币非法交易，封堵资金转移通道。",
        u"由金融监管部门牵头，穿透空壳公司和嵌套账户，追踪涉案资金去向。",
        u"由人民银行牵头，健全跨境结算体系，降低对单一结算通道的依赖。",
        u"由监委和公安部门牵头，深化追赃追逃国际合作，全力做好挽损止损。",
    ],
    "文化安全": [
        u"由宣传和国家安全部门牵头，跟踪渗透手法更新，动态做好识别防范。",
        u"由宣传和文旅部门牵头，做强正面文化供给，厚植主流价值认同。",
        u"由网信部门牵头，压实平台审核责任，阻断渗透内容传播链条。",
        u"由文旅和文物部门牵头，保护文化符号资源，防止被恶意借用。",
        u"由宣传和教育部门牵头，及时揭批软性渗透，提高公众辨别和免疫能力。",
    ],
    "政治安全": [
        u"由国家安全机关牵头，紧盯源头组织和人员脉络，动态掌握活动动向。",
        u"由网信部门牵头，前移监测巡查触角，填补网络平台和私密群组盲区。",
        u"由公安和金融部门牵头，深挖资金输送链路，切断经费保障。",
        u"由国安办牵头，预置敏感节点预案，确保风险苗头早发现早控制。",
        u"由国家安全机关牵头，依规移送有权机关，依法开展核查处置。",
    ],
}


def build_advices(domain, n_risks):
    """对策：动宾主旨句 + 确定性模板；6 条，条数与风险对齐（服从事实，可不等长）。"""
    _base_heads = ag.DOMAIN_ADVICE_HEADS.get(domain, ag.DOMAIN_ADVICE_HEADS["政治安全"])
    heads = sl.advice_heads_6(domain, _base_heads)
    bodies = list(_ADVICE_BODY.get(domain, _ADVICE_BODY["政治安全"]))
    bodies = bodies + [sl.ADVICE_BODY_EXTRA.get(domain, sl.ADVICE_BODY_EXTRA["政治安全"])]
    n = min(len(heads), len(bodies), max(3, n_risks))
    return [[heads[i], bodies[i]] for i in range(n)]


# ---------------------------------------------------------------- 单条成稿
def gen_one_article(r):
    """对一条线索生成完整稿件；不达标返回 None（宁缺毋滥，不机械拼接）。"""
    cid = r['id']
    # 题材准入硬门：非安全题材直接放弃
    admit, admit_why = security_admit(r)
    if not admit:
        return None, admit_why
    # 领域
    domain = ag.classify_domain(r)
    bd = ag.body_domain_vote(r)
    if bd:
        domain = bd
    # 候选池（只取一次）
    cands = _candidate_sents(r)
    if len(cands) < 4:
        return None, '可直抄事实句不足'
    # 正文（按 grade 决定目标字数/锚点）
    target = gd._BODY_MIN
    anchor_min = gd._ANCHOR_MIN
    basics, n_anch, basics_used = build_basics(cands, target, anchor_min, gd._ANCH_ORG, gd._ANCH_NUM)
    if len(basics_used) < 4:
        return None, '可直抄事实句不足'
    # 正文主体汉字不足 470（B档最低线）直接放弃，不写盘
    _bhan = len(qc_body._HAN.findall(basics))
    if _bhan < 470:
        return None, u'正文不足470(%d)' % _bhan
    # 分线：在合格安全料内部按标题/正文信号路由到 L1-L7
    style = sl.route_style(r)
    # 标题：按线构造（规则表），核心词须在正文、过分线 title_ok_style
    title = sl.build_title_style(style, r, basics)
    if not title:
        return None, u'无匹配%s标题规则' % style
    # 引言：按线模板（日期+据媒体+点题句+按线判断）
    media = clean_source(r.get('source'))
    dt = ag.parse_dt(r.get('published')) if hasattr(ag, 'parse_dt') else None
    if not dt:
        import tier_enqueue as te
        dt = te.parse_dt(r.get('published'))
    dstr = u'%d年%d月%d日，' % (dt.year, dt.month, dt.day) if dt else ''
    intro = sl.build_intro_style(style, r, basics, media, dstr)
    # 风险（直抄句，强制锚点，可复用 basics，6 条主旨句）
    risks = build_risks(domain, cands, set(basics_used), gd._ANCH_ORG, gd._ANCH_NUM)
    if len(risks) < 3:
        return None, '可锚定风险不足(%d)' % len(risks)
    # 对策（6 条）
    advices = build_advices(domain, len(risks))
    a = {
        'title': title,
        'intro': intro,
        'basics': basics,
        'chain': '',
        'risks': risks,
        'advices': advices,
        'analysis': '',
        'clue_id': cid,
        'url': r.get('url') or '',
        'source': clean_source(r.get('source')),
        'date': r.get('published') or '',
        'fresh': gd._fresh_of(str(r.get('published') or '')[:10]),
        'domain': domain,
        'style': style,
        'sentence_type': sl.STYLES[style][2],
        'auto': 1,
        'mode': 'newgen',
    }
    return a, ''


def build_intro(r, basics, title):
    """严格模板引言：日期+据媒体报道 + 与标题对齐的原文点题句 + 本质判断；控制 60-90 字。"""
    media = clean_source(r.get('source'))
    dstr = ''
    dt = ag.parse_dt(r.get('published')) if hasattr(ag, 'parse_dt') else None
    if not dt:
        import tier_enqueue as te
        dt = te.parse_dt(r.get('published'))
    if dt:
        dstr = u'%d年%d月%d日，' % (dt.year, dt.month, dt.day)
    # 标题核心 bigram（去掉"警惕"），用于点题句对齐
    tcore = re.sub(u'[^一-鿿]', '', title)[2:]
    tgrams = [tcore[i:i + 2] for i in range(len(tcore) - 1)]
    sents = [s.strip() for s in re.split(u'[。；]', basics) if 16 <= len(s.strip()) <= 60]
    # 优先：含锚点且命中标题核心词最多的句子
    point, bestscore = '', 0
    for s in sents:
        if not (gd._ANCH_ORG.search(s) or gd._ANCH_NUM.search(s)):
            continue
        score = sum(1 for g in tgrams if g in s)
        if score > bestscore:
            point, bestscore = s, score
    # 兜底：第一个含锚点的句子
    if not point:
        for s in sents:
            if gd._ANCH_ORG.search(s) or gd._ANCH_NUM.search(s):
                point = s
                break
    if not point:
        point = basics.split('。')[0][:50]
    intro = u'%s据%s报道，%s。这是相关动向被安全化的新动作，需持续跟踪评估。' % (dstr, media, point)
    return intro


def _same_event(title, other):
    """两个标题是否同一事件：共享长度≥3 的连续中文子串，或 bigram Jaccard 较高。"""
    zh = re.sub(u"[^一-鿿]", "", title)
    oz = re.sub(u"[^一-鿿]", "", other)
    for i in range(len(zh) - 2):
        if zh[i:i + 3] in oz:
            return True
    bg = set(zh[i:i + 2] for i in range(max(0, len(zh) - 1)))
    ob = set(oz[i:i + 2] for i in range(max(0, len(oz) - 1)))
    if bg and ob:
        j = len(bg & ob) / len(bg | ob)
        if j > 0.45:
            return True
    return False


# ---------------------------------------------------------------- 批量主函数
def main():
    n_limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    icon = sqlite3.connect('/opt/intelhub/intel.db')
    icon.row_factory = sqlite3.Row
    used = set(open('/opt/intelhub/deliver/articles/.used_ids.txt', encoding='utf-8').read().split())
    rows = icon.execute(
        "select * from items where coalesce(usable,0)=1 and coalesce(sensitive,0)=0 "
        "order by published desc").fetchall()
    ok_n, fail = 0, {}
    seen_titles = set()
    events = []  # 每项 [代表标题list, 该簇已出篇数]
    style_counts = {}  # 各线已产出篇数（含磁盘存量），用于配额
    out_dir = '/opt/intelhub/deliver/articles'
    # 从磁盘已有 newgen 稿加载标题/事件，防跨批次重复与同事件扎堆
    import glob as _glob
    for _ef in _glob.glob(out_dir + '/artauto_*.json'):
        try:
            _ea = json.load(open(_ef, encoding='utf-8'))
        except Exception:
            continue
        if _ea.get('mode') == 'newgen':
            seen_titles.add(_ea['title'])
            events.append([[_ea['title']], 1])
            if _ea.get('style'):
                style_counts[_ea['style']] = style_counts.get(_ea['style'], 0) + 1
    for row in rows:
        if ok_n >= n_limit:
            break
        r = dict(row)
        if r['id'] in used:
            continue
        # 7 天硬线：只出 7 天内的新料，不翻旧账
        if gd._fresh_of(str(r.get('published') or '')[:10]) == 'old':
            continue
        # 按正文汉字数选料（lang 标签不可靠），只处理中文主导的料
        if len(qc_body._HAN.findall(r.get('content') or '')) < 300:
            continue
        try:
            a, why = gen_one_article(r)
        except Exception as e:
            a, why = None, '异常:' + str(e)[:30]
        if not a:
            fail[why[:24]] = fail.get(why[:24], 0) + 1
            continue
        if a['title'] in seen_titles:
            fail['重复标题'] = fail.get('重复标题', 0) + 1
            continue
        # 配额软控：L5 暂缓不出；其余线占比明显超目标（相对超配约一半）才跳过，兼顾纠偏与冲量
        _st = a['style']
        _quota = sl.STYLES[_st][1]
        if _quota <= 0:
            fail['L5暂缓'] = fail.get('L5暂缓', 0) + 1
            continue
        _grand = sum(style_counts.values())
        # 起步阶段（有 style 的产出不足 3 篇）不启用占比控制，避免第一条即被误卡
        if _grand >= 3:
            _ratio = (style_counts.get(_st, 0) + 1) / (_grand + 1)
            if _ratio > _quota * 1.5:
                fail['配额超限'] = fail.get('配额超限', 0) + 1
                continue
        # 事件聚类：同事件最多保留 2 篇，防扎堆
        hit = None
        for ev in events:
            if any(_same_event(a['title'], t) for t in ev[0]):
                hit = ev
                break
        if hit is not None:
            if hit[1] >= 2:
                fail['同事件超限'] = fail.get('同事件超限', 0) + 1
                continue
            hit[0].append(a['title'])
            hit[1] += 1
        else:
            events.append([[a['title']], 1])
        seen_titles.add(a['title'])
        slug = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:16]
        fp = '%s/artauto_%s.json' % (out_dir, slug)
        json.dump(a, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        # 回写已用清单，防重复出稿
        with open('/opt/intelhub/deliver/articles/.used_ids.txt', 'a', encoding='utf-8') as uf:
            uf.write(a['clue_id'] + '\n')
        used.add(a['clue_id'])
        ok_n += 1
        style_counts[_st] = style_counts.get(_st, 0) + 1
        print('成稿 %s | %s | %s' % (a['clue_id'][:8], _st, a['title'][:28]))
    print('新生成器产出 %d 篇；各线分布 %s；放弃原因 %s' % (ok_n, style_counts, fail))


if __name__ == '__main__':
    main()
