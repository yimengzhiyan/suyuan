"""构建评测集：从辟谣平台与官方发布源采集带「原站点标签」的网络传闻。

    .venv/bin/python eval/build_dataset.py [--per-label 20] [--max-search 145] [--no-cache]

- 不实组：对中国互联网联合辟谣平台（piyao.org.cn）站内检索（腾讯较真 vp.fact.qq.com 的站内检索加 Freshness=y1 无结果、
  不加则只返回 2015~2020 年旧文，与「近一年」要求冲突，故未纳入检索计划），
  由大模型判断该文章是否「明确判定某条具体传闻为谣言/不实」，是则把传闻本身改写成「网传：……」。
  标签来自辟谣文章本身，source 为该文章 URL。
- 属实组：对中国政府网（www.gov.cn）、新华网（news.cn / xinhuanet.com）及 Industry=gov 检索近一年的具体政策/事实型新闻，
  由大模型把核心事实改写为「网传：……」口吻。标签来自官方原文本身，source 为原文 URL。
- 每条入选前再做一次「改写忠实度」复核调用；同一话题最多 2 条，同一事件只留 1 条。
- 搜索走 YuanbaoSearch 磁盘缓存（.cache/search），大模型走本脚本的磁盘缓存（.cache/llm_dataset），重复运行不花额度。

输出：
  eval/dataset.jsonl             首行 _comment，随后 f-xxx（不实）与 t-xxx（属实）
  eval/dataset_candidates.jsonl  所有候选及其状态（accepted / rejected / skipped）与原因
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)  # search.py 的缓存目录是相对路径
sys.path.insert(0, str(ROOT))

import suyuan  # noqa: E402,F401  —— 触发 load_dotenv
from suyuan.llm import LLM, JSON_INSTRUCTION, parse_json_loose  # noqa: E402
from suyuan import search as search_mod  # noqa: E402
from suyuan.search import SearchError, YuanbaoSearch  # noqa: E402

TOPICS = [
    "医保", "社保养老金", "高考中考", "房贷房产", "交通高速", "食品安全", "健康养生", "台风地震灾害",
    "个税五险一金", "高铁民航", "快递外卖", "征兵入伍", "电动车新规", "教育双减", "AI人工智能",
    "明星名人", "疫苗流感", "通信诈骗",
]

# 不实组：辟谣平台站内检索词（主检索 + 不足时的补充检索）
DEBUNK_QUERIES = {
    "医保": ["医保", "网传 医保 不实", "医保 谣言"],
    "社保养老金": ["养老金", "网传 养老金 上调 不实", "社保 谣言"],
    "高考中考": ["高考 中考", "网传 高考 系谣言", "高考 谣言"],
    "房贷房产": ["房贷 房产", "网传 公积金 房贷 不实", "房产 谣言"],
    "交通高速": ["高速 交通", "网传 高速 免费 不实", "交通 谣言"],
    "食品安全": ["食品安全", "网传 食品 系谣言", "食品 谣言"],
    "健康养生": ["健康 养生", "网传 医院 医生 系谣言", "养生 谣言"],
    "台风地震灾害": ["台风 地震", "网传 地震 不实", "地震 谣言"],
    "个税五险一金": ["个税 公积金", "网传 个税 退税 不实", "五险一金 谣言"],
    "高铁民航": ["高铁 民航", "网传 高铁 火车票 不实", "航班 谣言"],
    "快递外卖": ["快递 外卖", "网传 快递 停运 不实", "外卖 谣言"],
    "征兵入伍": ["征兵 入伍", "网传 征兵 退役军人 不实", "征兵 谣言", "网传 部队 军人 谣言"],
    "电动车新规": ["电动车", "网传 电动车 新规 不实", "电动自行车 谣言"],
    "教育双减": ["教育 学校 双减", "网传 教育部 学校 不实", "中小学 谣言", "网传 开学 放假 学校 不实"],
    "AI人工智能": ["AI 人工智能", "网传 AI 合成 不实", "AI 谣言"],
    "明星名人": ["明星 名人", "网传 明星 去世 谣言", "明星 谣言", "网传 演员 歌手 不实"],
    "疫苗流感": ["疫苗 流感", "网传 流感 疫苗 不实", "流感 谣言"],
    "通信诈骗": ["手机 通信 诈骗", "网传 手机号 运营商 不实", "诈骗 谣言"],
}

# 属实组：官方源检索 (query, 定向参数)。第一个为主检索，其余为补充检索
TRUE_QUERIES = {
    "医保": [("医保 通知 印发 起施行", {"site": "www.gov.cn"}), ("新华社 医保局 发布 通知", {"site": "news.cn"})],
    "社保养老金": [("基本养老金 调整 通知", {"site": "www.gov.cn"}), ("养老保险 新规 施行", {"industry": "gov"})],
    "高考中考": [("高考 报名 人数 教育部", {"site": "news.cn"}), ("高考 中考 招生 通知 印发", {"site": "www.gov.cn"})],
    "房贷房产": [("住房公积金 贷款 利率 调整 公告", {"industry": "gov"}), ("房贷 利率 下调 新华社", {"site": "news.cn"})],
    "交通高速": [("高速公路 收费 新规 正式施行", {"site": "www.gov.cn"}), ("交通运输部 宣布 正式启用", {"site": "news.cn"}), ("高速公路 节假日 免费通行 交通运输部", {"site": "news.cn"})],
    "食品安全": [("食品安全国家标准 发布 实施", {"site": "www.gov.cn"}), ("市场监管总局 食品 新规 施行", {"site": "xinhuanet.com"}), ("食品安全国家标准 公告 市场监管总局", {"site": "news.cn"})],
    "健康养生": [("国家卫生健康委 印发 方案 通知", {"site": "www.gov.cn"}), ("国家卫健委 发布 指南 新华社", {"site": "news.cn"})],
    "台风地震灾害": [("地震 级 中国地震台网 正式测定", {"site": "news.cn"}), ("台风 应急响应 启动 防总", {"site": "www.gov.cn"})],
    "个税五险一金": [("个人所得税 专项附加扣除 标准 调整", {"site": "www.gov.cn"}), ("公积金 缴存 新规 自起施行", {"industry": "gov"}), ("个人所得税 年度汇算 国家税务总局 公告", {"site": "www.gov.cn"})],
    "高铁民航": [("铁路 民航 新规 正式实施", {"site": "news.cn"}), ("高铁 开通运营 正式", {"site": "www.gov.cn"})],
    "快递外卖": [("快递 外卖 平台 规定 施行", {"site": "www.gov.cn"}), ("外卖骑手 社保 新华社", {"site": "news.cn"}), ("快递 新规 国家邮政局 施行", {"site": "news.cn"})],
    "征兵入伍": [("征兵 工作 开始 时间 通知", {"site": "www.gov.cn"}), ("征兵 体检 新规 国防部", {"site": "news.cn"}), ("征兵 报名 全国征兵网 截止", {"site": "news.cn"})],
    "电动车新规": [("电动自行车 国家标准 实施", {"site": "www.gov.cn"}), ("电动自行车 新规 起施行 公安", {"site": "news.cn"}), ("电动自行车 新国标 正式", {"site": "news.cn"}), ("电动自行车 强制性国家标准 新华社", {"site": "xinhuanet.com"})],
    "教育双减": [("教育部 通知 中小学 印发", {"site": "www.gov.cn"}), ("教育部 宣布 中小学 新华社", {"site": "news.cn"})],
    "AI人工智能": [("人工智能 管理办法 施行", {"site": "www.gov.cn"}), ("人工智能 生成内容 标识 正式", {"site": "news.cn"})],
    "明星名人": [("新华社 快讯 冠军 夺得", {"site": "news.cn"}), ("艺术家 获奖 宣布 新华社", {"site": "xinhuanet.com"})],
    "疫苗流感": [("疫苗 免疫规划 通知 纳入", {"site": "www.gov.cn"}), ("流感 疫苗 国家疾控局 发布", {"site": "news.cn"}), ("HPV疫苗 免费接种 国家免疫规划", {"site": "news.cn"})],
    "通信诈骗": [("电信网络诈骗 新规 施行 公安部", {"site": "www.gov.cn"}), ("工信部 通知 手机卡 正式", {"site": "news.cn"})],
}

# 话题关键词：标题、原文表述或改写文本中至少命中一个，防止大模型把擦边内容归到错误话题
TOPIC_KEYWORDS = {
    "医保": r"医保|医疗保障|医疗保险|报销",
    "社保养老金": r"养老|社保|社会保险|退休",
    "高考中考": r"高考|中考|考生|志愿|招生",
    "房贷房产": r"房贷|房产|住房|公积金|购房|楼市|房价|房屋",
    "交通高速": r"高速|交通|道路|公路|驾驶|驾照|车牌|违章",
    "食品安全": r"食品|食用|饮料|餐|配料|添加剂",
    "健康养生": r"健康|养生|医生|疾病|医院|吸氧|饮食|睡眠|康复|护理",
    "台风地震灾害": r"台风|地震|洪|汛|暴雨|灾",
    "个税五险一金": r"个税|个人所得税|退税|公积金|五险一金|专项附加扣除",
    "高铁民航": r"高铁|铁路|火车|列车|12306|航班|民航|机场|登机|乘机",
    "快递外卖": r"快递|外卖|骑手|配送|邮政",
    "征兵入伍": r"征兵|入伍|兵役|军人|部队|退役|参军",
    "电动车新规": r"电动车|电动自行车|电瓶车|电动摩托",
    "教育双减": r"教育|学校|学生|中小学|双减|课外|教师",
    "AI人工智能": r"AI|人工智能|智能|大模型|合成|生成",
    "明星名人": r"明星|演员|歌手|名人|冠军|运动员|艺人|导演|去世|逝世|选手",
    "疫苗流感": r"疫苗|流感|接种|病毒|传染|疾控|免疫",
    "通信诈骗": r"诈骗|电信|手机|通信|运营商|短信|号码",
}
TOPIC_DESC = {
    "教育双减": "教育双减（教育部门、学校、学生相关的政策与管理）",
    "征兵入伍": "征兵入伍（征兵、兵役、军人、退役军人、部队）",
    "明星名人": "明星名人（明星、演员、歌手、知名运动员等公众人物）",
    "AI人工智能": "AI人工智能（人工智能技术、AI生成内容及其管理）",
    "台风地震灾害": "台风地震灾害（台风、地震、洪涝等自然灾害）",
    "个税五险一金": "个税五险一金（个人所得税、社保公积金缴存）",
}
SCIENCE_COLUMN_RE = re.compile(r"今日【|节气|冷知识|小课堂")  # 节气/科普栏目，多为俗语或知识类

MAX_PER_TOPIC = 2
MAX_EVAL_PER_TOPIC = 12      # 每组每话题最多送大模型评审的候选数
PER_STAGE = 4                # 每个检索词最多评审几条候选，仍无收获就换下一个检索词
ROUNDUP_RE = re.compile(r"辟谣榜|盘点|一周|月度|这些谣言|……|\.\.\.|汇总|合集|十大|典型案|优秀作品|获奖作品|[0-9一二三四五六七八九十两]+起")
CONCLUSION_RE = re.compile(r"谣言|辟谣|不实|虚假|假的|假消息|系谣|属实|真相|核实|官方回应|求证")

LLM_CACHE = ROOT / ".cache" / "llm_dataset"

# --------------------------------------------------------------------------- prompts
DEBUNK_SYSTEM = """你是严谨的事实核查数据标注员。给你一篇来自辟谣平台的文章（标题、日期、正文摘录），以及当前话题和已入选传闻列表。
请判断这篇文章是否「明确判定某条具体传闻为谣言/不实/虚假」：
- 合格：文章明确说某条具体说法是谣言、不实、虚假、编造、诈骗信息、系误传且被否定。
- 不合格：结论是「部分属实」「误读/曲解但有一定依据」「仍在调查/求证」「纯科普知识或民间俗语/节气说法」「提醒类无具体传闻」「多条谣言合集无法确定主条」「传闻不具体」。
- 不合格：所谓「传闻」只是诈骗广告、售卖信息、诱导转账话术、个人发帖引流，而不是一条关于事实的说法（某事发生了 / 某机构出台了某政策 / 某数据为真）。
必须选择文章标题所指的那条传闻（每日辟谣汇总页正文可能附带其他条目，不能选标题以外的条目；标题未指向具体传闻则不合格）。
若合格，只挑被辟谣的「一条」核心说法（不要把多条说法拼在一起），改写成一句在群聊里传播的口吻文本：以「网传：」开头，30~80 个汉字，保留原传闻中的人物、机构、地点、数字、时间等具体细节；
不得出现辟谣结论或「谣言/不实/辟谣/假」等字样，也不要加入原文没有的细节。
另外请判断：
- on_topic：该传闻的核心主体是否就是给定话题本身（如话题「电动车新规」必须是关于电动车管理规定的传闻，话题「快递外卖」必须是关于快递或外卖行业的传闻），仅擦边提及算 false；
- obvious：一个普通成年人不查资料、仅凭常识是否就能一眼看出它是假的（如明显违背科学常识的荒诞说法），是则 true；
- specific：传闻是否具体、可通过搜索核实（有明确主体、事件或数字）；
- duplicate_of：若与「已入选传闻」中某条是同一事件/同一说法，填其 id，否则 null。
输出 JSON：{"qualified": true/false, "verdict_type": "谣言/不实|部分属实|误读|仍在求证|科普|合集|其他", "rumor_original": "原文中对传闻的表述", "text": "网传：……（不合格时为空）", "on_topic": true/false, "obvious": true/false, "specific": true/false, "duplicate_of": null, "reason": "一句话说明"}"""

TRUE_SYSTEM = """你是严谨的事实核查数据标注员。给你一篇官方或中央媒体发布的新闻（标题、日期、正文摘录），以及当前话题和已入选条目列表。
请判断它是否是一条「具体的政策或事实型新闻」：有明确的发布机构/主体，并且有具体数字、日期或具体措施；空泛表态、会议讲话、成就综述、观点评论、规划愿景类不合格。
所选事实必须是「已经发生 / 已经发布或施行」的事（如某文件已印发、某标准自某日起施行、某事件已发生、某人已夺冠），不要选「到20XX年将……」「十五五期间将……」这类未来目标；
所选事实的发生/发布时间应在 {cutoff} 之后；个人消费纠纷、记者暗访等个案故事不合格；法规条文中纯技术性的引用修改不合格。
若合格，把其中一个最核心、可独立核实的事实改写成一句在群聊里传播的口吻文本：以「网传：」开头，30~80 个汉字。
要求：内容必须与原文事实完全一致——不能夸大、不能改数字、不能改主体、不能改时间、不能补充原文没有的信息；时间用绝对日期或年份（不要写「明年」「下月」这类相对时间）；不要写「官方证实」之类的结论。
另外请判断：
- on_topic：该事实的核心主体是否就是给定话题本身（如话题「电动车新规」必须是关于电动自行车/电动车的规定，「交通高速」必须是关于道路交通或高速公路的，「食品安全」必须是关于食品安全监管或标准的），仅擦边提及算 false；
- obvious：普通成年人不查资料是否就能凭常识确定它是真的（如众所周知的节日、常识），是则 true；
- specific：是否具体、可通过搜索核实；
- duplicate_of：若与「已入选条目」中某条是同一事件/同一政策，填其 id，否则 null。
另给出 fact_date：该事实发生或文件发布的日期（不是施行日期），格式 YYYY-MM-DD，只知道月份则 YYYY-MM。
输出 JSON：{"qualified": true/false, "fact_date": "YYYY-MM-DD", "fact_original": "原文中支撑该事实的句子", "text": "网传：……（不合格时为空）", "on_topic": true/false, "obvious": true/false, "specific": true/false, "duplicate_of": null, "reason": "一句话说明"}"""

CHECK_SYSTEM_DEBUNK = """你是数据质检员。给你一篇辟谣文章的正文摘录和一条改写出来的「传闻文本」。
请检查：1) 传闻文本是否忠实复述了文章所辟谣的那条说法（主体、数字、时间等细节没有被改动或编造）；2) 文章是否明确判定这条说法为谣言/不实/虚假（而不是部分属实或仍在求证）；3) 传闻文本中是否没有泄露辟谣结论。
输出 JSON：{"ok": true/false, "issues": "发现的问题，没有则为空字符串"}"""

CHECK_SYSTEM_TRUE = """你是数据质检员。给你一篇官方新闻的正文摘录和一条改写出来的「传闻文本」。
请逐项检查传闻文本中的每个事实要素（主体、数字、日期、措施、范围）是否都能在原文中找到依据且完全一致，有无夸大、篡改、张冠李戴或补充原文没有的信息。
同时判断它是否是一条具体、已发生的事实（如某文件已印发、某标准已发布、某事件已发生、某数据已公布），而不是成就综述、工作思路、表态或「将……」的规划目标；不是则 ok=false。
输出 JSON：{"ok": true/false, "issues": "发现的问题，没有则为空字符串"}"""


# --------------------------------------------------------------------------- helpers
class CachedLLM:
    """在 suyuan.llm.LLM 外面加一层磁盘缓存，重复运行不重复扣费。"""

    def __init__(self, use_cache: bool = True):
        self.llm = LLM()
        self.use_cache = use_cache
        self.cache_hits = 0
        LLM_CACHE.mkdir(parents=True, exist_ok=True)

    @property
    def calls(self) -> int:
        return self.llm.calls

    def chat_json(self, system: str, user: str, max_tokens: int = 800) -> dict:
        key = hashlib.sha1(f"{self.llm.model}\n{system}\n{user}\n{max_tokens}".encode("utf-8")).hexdigest()
        f = LLM_CACHE / f"{key}.json"
        if self.use_cache and f.exists():
            self.cache_hits += 1
            return parse_json_loose(f.read_text("utf-8"))
        text = self.llm.chat(system + JSON_INSTRUCTION, user, temperature=0.1, max_tokens=max_tokens)
        data = parse_json_loose(text)  # 解析失败不写缓存
        if self.use_cache:
            f.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        return data


def parse_date(s: str) -> datetime | None:
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def date_from_url(url: str) -> datetime | None:
    """gov.cn / news.cn 的 URL 里通常带 /YYYYMMDD/ 或 /YYYYMM/。"""
    m = re.search(r"/(20\d{2})(\d{2})(\d{2})?/", url or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def hanzi_len(s: str) -> int:
    return len(re.sub(r"\s", "", s))


def clean_title(t: str) -> str:
    return re.sub(r"_[^_]*_?中国政府网$", "", t or "").strip()


class Builder:
    def __init__(self, args):
        self.args = args
        self.client = YuanbaoSearch(use_cache=not args.no_cache)
        self.llm = CachedLLM(use_cache=not args.no_cache)
        self.now = datetime.now()
        self.cutoff = self.now - timedelta(days=365)
        self.seen_urls: set[str] = set()
        self.candidates: list[dict] = []   # 所有候选（含状态）
        self.search_log: list[dict] = []
        self.search_cached = 0

    # ---- 搜索 ----
    def search(self, query: str, **kw) -> list:
        if self.client.calls >= self.args.max_search and not self._is_cached(query, cnt=20, **kw):
            print(f"  [搜索额度保护] 已达 {self.args.max_search} 次真实调用，跳过：{query} {kw}", file=sys.stderr)
            return []
        try:
            res = self.client.search(query, cnt=20, **kw)
        except SearchError as e:
            print(f"  搜索失败：{query} {kw} -> {e}", file=sys.stderr)
            return []
        self.search_cached += res.cached
        self.search_log.append({"query": query, **kw, "n": len(res.pages), "cached": res.cached})
        return res.pages

    def _is_cached(self, query: str, **kw) -> bool:
        """与 YuanbaoSearch.search 的缓存键保持一致：缓存命中不受额度保护限制。"""
        if not self.client.use_cache:
            return False
        keymap = {"site": "Site", "cnt": "Cnt", "industry": "Industry", "freshness": "Freshness", "mode": "Mode"}
        payload = {"Query": query, **{keymap[k]: v for k, v in kw.items() if v}}
        return (search_mod.CACHE_DIR / f"{self.client._cache_key(payload)}.json").exists()

    def add_candidates(self, group: str, topic: str, pages, query: str, params: dict) -> list[dict]:
        out = []
        for p in pages:
            url = (p.url or "").strip()
            if not url or url in self.seen_urls:
                continue
            self.seen_urls.add(url)
            d = parse_date(p.date) or date_from_url(url)
            c = {
                "group": group, "topic": topic, "title": clean_title(p.title), "url": url, "site": p.site,
                "date": d.strftime("%Y-%m-%d") if d else (p.date or ""), "snippet": p.snippet[:300],
                "query": query, "params": params, "status": "pending", "reason": "",
                "_content": p.snippet, "_date": d,
            }
            # 规则预筛
            if not re.match(r"^https?://[A-Za-z0-9.-]+(?::\d+)?/", url):
                c["status"], c["reason"] = "rejected", "URL 格式异常"
            elif group == "debunk" and "vp.fact.qq.com" not in url and "piyao.org.cn" not in url:
                c["status"], c["reason"] = "rejected", "非辟谣平台页面"
            elif not d:
                c["status"], c["reason"] = "rejected", "无法解析日期"
            elif group == "debunk" and SCIENCE_COLUMN_RE.search(c["title"]):
                c["status"], c["reason"] = "rejected", "节气/科普栏目，多为俗语或知识类，非具体传闻"
            elif ROUNDUP_RE.search(c["title"]):
                c["status"], c["reason"] = "rejected", "合集/盘点类标题，难以对应单条传闻"
            elif len(p.snippet) < (80 if group == "debunk" else 30):
                c["status"], c["reason"] = "rejected", "正文摘录过短"
            elif d < self.cutoff:
                c["status"], c["reason"] = "rejected", "发布超过一年"
            elif group == "true" and re.search(r"/(?:index|list|node)[^/]*\.htm|/liebiao/?$", url):
                c["status"], c["reason"] = "rejected", "栏目/列表页"
            self.candidates.append(c)
            out.append(c)
        return out

    # ---- 大模型评审 ----
    def review(self, c: dict, accepted: list[dict]) -> dict | None:
        group = c["group"]
        acc_list = "\n".join(f"{a['id']}: {a['text']}" for a in accepted) or "（无）"
        user = (
            f"话题：{TOPIC_DESC.get(c['topic'], c['topic'])}\n标题：{c['title']}\n日期：{c['date']}\nURL：{c['url']}\n"
            f"正文摘录：\n{c['_content'][:1800]}\n\n已入选条目：\n{acc_list}"
        )
        system = DEBUNK_SYSTEM if group == "debunk" else TRUE_SYSTEM.replace("{cutoff}", self.cutoff.strftime("%Y-%m-%d"))
        try:
            r = self.llm.chat_json(system, user)
        except Exception as e:  # noqa: BLE001
            c["status"], c["reason"] = "rejected", f"大模型评审失败：{e}"
            return None
        c["llm_review"] = r
        text = re.sub(r"^网传\s*[:：]\s*", "网传：", str(r.get("text") or "").strip())
        reason = str(r.get("reason") or "")
        fail = None
        if not r.get("qualified"):
            fail = f"不合格（{r.get('verdict_type', '')}）：{reason}" if group == "debunk" else f"不合格：{reason}"
        elif not r.get("on_topic"):
            fail = f"话题不符：{reason}"
        elif r.get("obvious"):
            fail = f"凭常识一眼可判：{reason}"
        elif r.get("specific") is False:
            fail = f"不够具体：{reason}"
        elif not re.search(TOPIC_KEYWORDS[c["topic"]], f"{c['title']} {text} {r.get('rumor_original') or r.get('fact_original') or ''}"):
            fail = "话题关键词未命中（大模型判 on_topic 但标题与文本均不含话题词）"
        elif group == "true" and (fd := parse_date(str(r.get("fact_date") or "") + "-01")) and fd < self.cutoff.replace(day=1):
            fail = f"事实发生时间 {r.get('fact_date')} 早于近一年"
        elif r.get("duplicate_of"):
            fail = f"与 {r.get('duplicate_of')} 同一事件"
        elif not text.startswith("网传："):
            fail = f"改写格式不符：{text[:40]}"
        elif not 30 <= hanzi_len(text) <= 80:
            fail = f"改写长度 {hanzi_len(text)} 不在 30~80"
        elif group == "debunk" and CONCLUSION_RE.search(text[3:]):
            fail = f"改写泄露结论字样：{text}"
        if fail:
            c["status"], c["reason"] = "rejected", fail
            return None
        # 忠实度复核
        chk_sys = CHECK_SYSTEM_DEBUNK if group == "debunk" else CHECK_SYSTEM_TRUE
        try:
            chk = self.llm.chat_json(chk_sys, f"标题：{c['title']}\n正文摘录：\n{c['_content'][:1800]}\n\n传闻文本：{text}", max_tokens=400)
        except Exception as e:  # noqa: BLE001
            c["status"], c["reason"] = "rejected", f"复核调用失败：{e}"
            return None
        c["llm_check"] = chk
        if not chk.get("ok"):
            c["status"], c["reason"] = "rejected", f"复核未通过：{chk.get('issues', '')}"
            return None
        c["text"] = text
        return c

    # ---- 一组的选择流程 ----
    def build_group(self, group: str) -> list[dict]:
        n_target = self.args.per_label
        label = "不实" if group == "debunk" else "属实"
        prefix = "f" if group == "debunk" else "t"
        pools: dict[str, list[dict]] = {t: [] for t in TOPICS}
        evaluated = {t: 0 for t in TOPICS}
        stage = {t: 0 for t in TOPICS}  # 已执行到第几个检索
        accepted: list[dict] = []
        count = {t: 0 for t in TOPICS}

        def plan(topic):
            if group == "debunk":
                return [(q, {"site": "piyao.org.cn", "freshness": "y1"}) for q in DEBUNK_QUERIES[topic]]
            return [(q, {**p, "freshness": "y1"}) for q, p in TRUE_QUERIES[topic]]

        stage_eval: dict[tuple, int] = {}

        def fetch_next(topic) -> bool:
            qs = plan(topic)
            if stage[topic] >= len(qs):
                return False
            q, params = qs[stage[topic]]
            stage[topic] += 1
            pages = self.search(q, **params)
            for c in self.add_candidates(group, topic, pages, q, params):
                c["_stage"] = stage[topic]
                pools[topic].append(c)
            return True

        def try_topic(topic) -> bool:
            while evaluated[topic] < MAX_EVAL_PER_TOPIC:
                cur = stage[topic]
                pend_cur = [c for c in pools[topic] if c["status"] == "pending" and c["_stage"] == cur]
                # 当前检索词的候选评审满 PER_STAGE 条仍无收获（或已用完），就换下一个检索词
                if (not pend_cur or stage_eval.get((topic, cur), 0) >= PER_STAGE) and fetch_next(topic):
                    continue
                pend = [c for c in pools[topic] if c["status"] == "pending"]
                if not pend:
                    return False
                pend.sort(key=lambda c: (c["_stage"] != cur, -(c["_date"] or datetime.min).timestamp()))  # 近期优先
                c = pend[0]
                evaluated[topic] += 1
                stage_eval[(topic, c["_stage"])] = stage_eval.get((topic, c["_stage"]), 0) + 1
                print(f"  [{group}/{topic}] 评审 {c['date']} {c['title'][:40]}", file=sys.stderr)
                if self.review(c, accepted):
                    c["status"] = "accepted"
                    c["id"] = f"{prefix}-{len(accepted) + 1:03d}"
                    c["label"] = label
                    accepted.append(c)
                    count[topic] += 1
                    print(f"    ✓ {c['id']} {c['text']}", file=sys.stderr)
                    return True
                print(f"    ✗ {c['reason'][:80]}", file=sys.stderr)
            return False

        print(f"\n== {label}组：目标 {n_target} 条 ==", file=sys.stderr)
        for rnd in range(1, MAX_PER_TOPIC + 1):
            for topic in TOPICS:
                if len(accepted) >= n_target:
                    break
                if count[topic] < rnd:
                    try_topic(topic)
        for t in TOPICS:  # 剩余未评审的候选标记出来
            for c in pools[t]:
                if c["status"] == "pending":
                    c["status"], c["reason"] = "skipped", "未送评审（话题已满或总数已够）"
        if len(accepted) < n_target:
            print(f"!! {label}组只收集到 {len(accepted)} 条，少于目标 {n_target}", file=sys.stderr)
        return accepted

    def run(self):
        fake = self.build_group("debunk")
        true = self.build_group("true")
        today = self.now.strftime("%Y-%m-%d")
        comment = {
            "_comment": (
                f"由 eval/build_dataset.py 于 {today} 构建。不实组 {len(fake)} 条：来自中国互联网联合辟谣平台 piyao.org.cn"
                f"（腾讯较真 vp.fact.qq.com 站内检索近一年无结果，未采用）站内检索，标签取自辟谣文章本身的结论，source 为辟谣文章 URL；"
                f"属实组 {len(true)} 条：来自中国政府网 / 新华网 / 政务行业检索的近一年具体政策或事实新闻，标签取自官方原文，source 为原文 URL。"
                f"传闻文本 text 由大模型（{self.llm.llm.model}）改写为「网传：……」口吻并经第二次调用复核忠实度；"
                f"每话题最多 {MAX_PER_TOPIC} 条、同一事件只留 1 条。全部候选与拒绝原因见 eval/dataset_candidates.jsonl。"
            )
        }
        keep = ["id", "text", "label", "source", "title", "topic", "date"]
        with (ROOT / "eval" / "dataset.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps(comment, ensure_ascii=False) + "\n")
            for c in fake + true:
                row = {**c, "source": c["url"]}
                f.write(json.dumps({k: row[k] for k in keep}, ensure_ascii=False) + "\n")
        with (ROOT / "eval" / "dataset_candidates.jsonl").open("w", encoding="utf-8") as f:
            for c in self.candidates:
                f.write(json.dumps({k: v for k, v in c.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")

        from collections import Counter
        print("\n==== 完成 ====")
        print(f"不实 {len(fake)} 条，属实 {len(true)} 条 -> eval/dataset.jsonl")
        print(f"候选 {len(self.candidates)} 条 -> eval/dataset_candidates.jsonl "
              f"（{dict(Counter(c['status'] for c in self.candidates))}）")
        topic_cnt = Counter(c["topic"] for c in fake + true)
        print("话题分布：" + "，".join(f"{t} {topic_cnt.get(t, 0)}" for t in TOPICS))
        print(f"搜索：真实调用 {self.client.calls} 次，缓存命中 {self.search_cached} 次")
        print(f"大模型：真实调用 {self.llm.calls} 次，缓存命中 {self.llm.cache_hits} 次，tokens {self.llm.llm.tokens}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-label", type=int, default=20, help="每个标签的条数（默认 20）")
    ap.add_argument("--max-search", type=int, default=145, help="本次运行真实搜索调用上限")
    ap.add_argument("--no-cache", action="store_true", help="不读写搜索与大模型缓存")
    args = ap.parse_args()
    if args.per_label > len(TOPICS) * MAX_PER_TOPIC:
        ap.error(f"--per-label 最大 {len(TOPICS) * MAX_PER_TOPIC}")
    Builder(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
