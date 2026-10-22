"""主张抽取：把一段传闻拆成可检索、可核实的原子主张。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm import LLM

SYSTEM_PROMPT = """你是事实核查编辑。任务：从用户给出的网络传闻中抽取可以通过公开信息核实的事实性主张，并为每条主张设计搜索引擎检索词。

要求：
1. 最多抽取 3 条「原子主张」：每条只陈述一个可核实的事实（谁、在何时何地、做了什么/发生了什么、数字是多少）。
2. 忽略观点、情绪、号召转发、修辞夸张等无法核实的内容。
3. 保留原文中的关键实体（人名、机构、地名、产品、数字），不要添加原文没有的信息。
4. 为每条主张给出三种检索词：
   - core：核心事实检索词，6~15 个字，由关键实体+事件构成，不要带「网传」「据说」「震惊」等词；
   - debunk：用于查找辟谣/澄清的检索词，如「<核心事件> 辟谣」「<核心事件> 谣言」；
   - alt：换一种说法或从官方角度的检索词，如「<机构> 回应 <事件>」「<机构> 通报」。
5. topic 为整段传闻的主题，10 字以内。

输出 JSON 格式：
{"topic": "...", "claims": [{"text": "主张原子陈述", "entities": ["实体1", "实体2"], "time": "时间，没有则空字符串", "place": "地点，没有则空字符串", "queries": {"core": "...", "debunk": "...", "alt": "..."}}]}"""

# 规则退化时要去掉的噪声词
NOISE_WORDS = (
    "网传", "据说", "听说", "震惊", "速看", "紧急扩散", "紧急通知", "扩散", "转发", "重磅",
    "刚刚", "突发", "注意", "千万别", "赶紧", "必看", "惊呆", "【", "】", "！", "!",
)


@dataclass
class Claim:
    text: str
    entities: list[str] = field(default_factory=list)
    time: str = ""
    place: str = ""
    queries: dict[str, str] = field(default_factory=dict)  # core / debunk / alt


@dataclass
class ClaimSet:
    topic: str
    claims: list[Claim]
    raw_input: str
    warning: str = ""  # 大模型抽取失败、退化为规则时的原因


def _clean(text: str) -> str:
    s = text
    for w in NOISE_WORDS:
        s = s.replace(w, " ")
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ，。,.：:；;")
    return s


def fallback_claim(text: str) -> Claim:
    """不依赖大模型的规则抽取：去噪声词后取前 30 字作为核心检索词。"""
    cleaned = _clean(text)
    # 优先取第一句，避免截断到下一句中间
    first = re.split(r"[。！？!?\n]", cleaned)[0].strip() or cleaned
    core = first[:30] or text.strip()[:30]
    return Claim(
        text=first[:120] or text.strip()[:120],
        queries={"core": core, "debunk": f"{core} 辟谣", "alt": f"{core} 官方回应"},
    )


def _normalize_claim(d: dict, text: str) -> Claim | None:
    ctext = str(d.get("text") or "").strip()
    if not ctext:
        return None
    q = d.get("queries") or {}
    if not isinstance(q, dict):
        q = {}
    core = str(q.get("core") or "").strip() or _clean(ctext)[:30]
    core = _clean(core) or core
    queries = {
        "core": core,
        "debunk": str(q.get("debunk") or "").strip() or f"{core} 辟谣",
        "alt": str(q.get("alt") or "").strip() or f"{core} 官方回应",
    }
    ents = d.get("entities") or []
    if not isinstance(ents, list):
        ents = [str(ents)]
    return Claim(
        text=ctext,
        entities=[str(e) for e in ents if e],
        time=str(d.get("time") or ""),
        place=str(d.get("place") or ""),
        queries=queries,
    )


def extract_claims(llm: LLM | None, text: str) -> ClaimSet:
    """抽取主张；llm 为 None 或调用失败时退化为规则抽取。"""
    text = text.strip()
    warning = ""
    if llm is not None:
        try:
            data = llm.chat_json(SYSTEM_PROMPT, f"传闻原文：\n{text[:3000]}")
            claims = [c for c in (_normalize_claim(d, text) for d in (data.get("claims") or [])[:3] if isinstance(d, dict)) if c]
            if claims:
                topic = str(data.get("topic") or "").strip() or claims[0].queries["core"]
                return ClaimSet(topic=topic, claims=claims, raw_input=text)
            warning = "大模型未抽取到主张，已退化为规则抽取"
        except Exception as e:  # noqa: BLE001 —— 任何失败都退化为规则
            warning = f"主张抽取失败，已退化为规则抽取：{e}"
    c = fallback_claim(text)
    return ClaimSet(topic=c.queries["core"][:15], claims=[c], raw_input=text, warning=warning)
