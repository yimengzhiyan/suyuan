"""核心流水线：主张抽取 → 多路检索 → 证据合并分级 → 溯源时间线 → 判定 → 延伸话题。"""
from __future__ import annotations

import dataclasses
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from .claims import Claim, extract_claims
from .fetch import excerpt, fetch_text
from .llm import LLM
from .search import Page, YuanbaoSearch
from .sources import DEBUNK_SITES, canonical_url, domain_of, is_debunk_site, tier_name, tier_of

class SearchFatal(RuntimeError):
    """搜索服务不可用（Key 无效 / 未开通 / 欠费），整次核查应当终止。"""


VERDICTS = ("属实", "不实", "部分属实", "证据不足")
MAX_EVIDENCE_PER_CLAIM = 15  # 每条主张喂给大模型的证据上限
SNIPPET_CHARS = 300
ORIGIN_CANDIDATES = 12  # 交给大模型挑选「首发」的最早候选条数
DEEP_READ_PAGES = 4  # 判定前抓取原文的证据页数（每条主张），0 表示关闭

_DATE_RE = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
_DEBUNK_TITLE_RE = re.compile(r"辟谣|谣言|不实|假消息|澄清|网传.{0,10}(假|不属实)")


# ---- 数据结构 -------------------------------------------------------------
@dataclass
class Evidence:
    idx: int  # 全局引用编号，从 1 开始，判定时按 [idx] 引用
    claim_idx: int  # 对应第几条主张（从 0 开始）
    title: str
    url: str
    site: str
    date: str  # 接口返回的原始日期字符串
    date_parsed: date | None
    tier: int
    tier_name: str
    score: float
    snippet: str
    channels: list[str] = field(default_factory=list)
    is_debunk: bool = False


@dataclass
class TimelineItem:
    date: date
    title: str
    url: str
    site: str
    tier: int


@dataclass
class Extension:
    query: str
    items: list[dict] = field(default_factory=list)  # title/url/site/date


@dataclass
class Report:
    input_text: str
    topic: str = ""
    claims: list[Claim] = field(default_factory=list)
    verdict: str = "证据不足"
    confidence: float = 0.0
    reasoning: str = ""
    official_stance: str = "未检索到"
    origin: Evidence | None = None
    origin_kind: str = "background"  # rumor：最早转述传闻本身；background：只是最早的相关背景内容
    origin_note: str = ""
    key_evidence: list[Evidence] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    timeline: list[TimelineItem] = field(default_factory=list)
    extensions: list[Extension] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _jsonable(dataclasses.asdict(self))


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


# ---- 工具函数 -------------------------------------------------------------
def parse_date(s: str | None) -> date | None:
    """宽松解析 yyyy-mm-dd / yyyy/mm/dd / yyyy年m月d日，失败或明显异常返回 None。"""
    if not s:
        return None
    m = _DATE_RE.search(str(s))
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    if d.year < 1990 or d > date.today() + timedelta(days=1):
        return None
    return d


def _short_query(core: str, entities: list[str]) -> str:
    """把检索词压到 12 字以内：优先用实体拼接，否则截断 core。"""
    core = re.sub(r"[，。！？、；：,.!?;:\s]+", " ", core).strip()
    if len(core) <= 12:
        return core
    ents = [e for e in entities if e and len(e) <= 8]
    if ents:
        q = ""
        for e in ents:
            if len(q) + len(e) + 1 > 12:
                break
            q = f"{q} {e}".strip()
        if len(q) >= 4:
            return q
    return core[:12]


def _relevant(page: Page, claim: Claim) -> bool:
    """粗略相关性判断（仅用于溯源补搜）：命中任一实体，或与 core 检索词的二元字重合率 >= 0.3。"""
    text = f"{page.title} {page.snippet[:500]}"
    if claim.entities and any(e and e in text for e in claim.entities):
        return True
    core = re.sub(r"\s+", "", claim.queries.get("core", ""))
    grams = {core[i : i + 2] for i in range(len(core) - 1)}
    if not grams:
        return False
    return sum(g in text for g in grams) / len(grams) >= 0.3


# ---- 主流程 ---------------------------------------------------------------
class Verifier:
    def __init__(self, search: YuanbaoSearch, llm: LLM | None, deep_read: int = DEEP_READ_PAGES):
        """llm 为 None 时只做检索与分级，判定固定为「证据不足」。deep_read：每条主张抓取原文的页数。"""
        self.search = search
        self.llm = llm
        self.deep_read = deep_read

    # 单次检索：异常只记 warning，不中断
    def _search(self, report: Report, query: str, channel: str, **kw) -> list[Page]:
        if not query:
            return []
        try:
            res = self.search.search(query, channel=channel, **kw)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # Key 无效、未开通、欠费：继续跑只会得到一份全靠缓存拼出来的假结果，直接终止
            if any(code in msg for code in ("UnauthorizedOperation", "ResourceNotFound", "ResourceUnavailable", "AuthFailure")):
                raise SearchFatal(
                    "元宝搜索拒绝了请求（" + msg.split(":")[0].strip() + "）。请检查填写的元宝搜索 Key 是否正确、服务是否已开通、是否欠费。"
                ) from e
            report.warnings.append(f"检索失败 [{channel}] {query!r} {kw}: {e}")
            return []
        if res.cached:
            self._cached_hits += 1
        return res.pages

    def verify(self, text: str, progress: Callable[[str], None] | None = None) -> Report:
        say = progress or (lambda _msg: None)
        t0 = time.time()
        calls0 = self.search.calls
        llm_calls0 = self.llm.calls if self.llm else 0
        llm_tokens0 = self.llm.tokens if self.llm else 0
        self._cached_hits = 0
        self._deep_pages = 0

        report = Report(input_text=text.strip())

        # 1. 主张抽取
        say("抽取可核实主张…")
        cs = extract_claims(self.llm, text)
        report.topic, report.claims = cs.topic, cs.claims
        if cs.warning:
            report.warnings.append(cs.warning)
        for i, c in enumerate(cs.claims, 1):
            say(f"主张 {i}：{c.text}（检索词：{c.queries.get('core')}）")

        # 2. 多路检索 + 3. 按主张去重合并
        merged: list[dict[str, Evidence]] = []
        for ci, claim in enumerate(cs.claims):
            core, debunk = claim.queries.get("core", ""), claim.queries.get("debunk", "")
            say(f"主张 {ci + 1}：多路检索（混合 / 新闻 / 政务 / 辟谣）…")
            pages: list[Page] = []
            pages += self._search(report, core, "mixed", mode=2, cnt=20)
            pages += self._search(report, core, "news", industry="news", cnt=10)
            pages += self._search(report, core, "gov", industry="gov", cnt=10)
            pages += self._search(report, debunk, "debunk", mode=0, cnt=10)
            # 辟谣站点定向检索：站内索引小，长句检索词常常零命中，用更短的关键词
            short = _short_query(core, claim.entities)
            for site in DEBUNK_SITES:
                pages += self._search(report, short, "debunk_site", site=site, cnt=10)
            bucket: dict[str, Evidence] = {}
            for p in pages:
                self._merge(bucket, p, ci)
            merged.append(bucket)

        # 4. 溯源：找最早的一条，再在其之前 30 天窗口补搜一次
        say("构建溯源时间线…")
        dated = [e for b in merged for e in b.values() if e.date_parsed]
        if dated:
            earliest = min(dated, key=lambda e: e.date_parsed)
            claim = cs.claims[earliest.claim_idx]
            d1 = earliest.date_parsed
            window = f"{(d1 - timedelta(days=30)).isoformat()},{d1.isoformat()}"
            say(f"溯源补搜：{window}")
            for p in self._search(report, claim.queries.get("core", ""), "origin_probe", freshness=window, mode=0, cnt=10):
                if parse_date(p.date) and _relevant(p, claim):
                    self._merge(merged[earliest.claim_idx], p, earliest.claim_idx)

        # 排序并分配全局编号
        idx = 0
        llm_input: list[Evidence] = []
        for bucket in merged:
            items = sorted(bucket.values(), key=lambda e: (e.tier, -e.score))
            for e in items:
                idx += 1
                e.idx = idx
            report.evidence += items
            llm_input += items[:MAX_EVIDENCE_PER_CLAIM]

        dated = sorted((e for e in report.evidence if e.date_parsed), key=lambda e: (e.date_parsed, e.tier))
        report.timeline = [TimelineItem(e.date_parsed, e.title, e.url, e.site, e.tier) for e in dated]
        if dated:
            o = dated[0]
            report.origin = o
            report.origin_note = (
                f"搜索可见范围内最早的相关内容为 {o.date_parsed.isoformat()} {o.site}（{o.tier_name}）发布的《{o.title}》"
            )

        # 5. 判定
        if not llm_input:
            report.reasoning = "未检索到任何相关证据。"
        elif self.llm is None:
            report.reasoning = "未启用大模型，仅完成检索与信源分级。"
        else:
            deep = self._deep_read(report, llm_input, say) if self.deep_read else {}
            say(f"大模型基于 {len(llm_input)} 条证据判定…")
            self._judge(report, llm_input, origin_candidates=dated[:ORIGIN_CANDIDATES], deep=deep)

        # 6. 延伸话题
        if self.llm is not None:
            say("生成延伸话题…")
            for q in self._extension_queries(report):
                pages = self._search(report, q, "extend", mode=2, cnt=10)
                report.extensions.append(Extension(q, [
                    {"title": p.title, "url": p.url, "site": p.site, "date": p.date} for p in pages[:3]
                ]))

        # 7. 统计
        tiers = {tier_name(t): sum(e.tier == t for e in report.evidence) for t in range(1, 6)}
        report.stats = {
            "search_calls": self.search.calls - calls0,
            "cached_hits": self._cached_hits,
            "llm_calls": (self.llm.calls - llm_calls0) if self.llm else 0,
            "llm_tokens": (self.llm.tokens - llm_tokens0) if self.llm else 0,
            "evidence_count": len(report.evidence),
            "evidence_to_llm": len(llm_input),
            "deep_read_pages": self._deep_pages,
            "tier_distribution": tiers,
            "elapsed": round(time.time() - t0, 2),
        }
        say("完成")
        return report

    # ---- 子步骤 -----------------------------------------------------------
    @staticmethod
    def _merge(bucket: dict[str, Evidence], p: Page, claim_idx: int) -> None:
        """按 url 去重：保留 score 最高的那条内容，channel 列表合并。"""
        if not p.url:
            return
        key = canonical_url(p.url)
        old = bucket.get(key)
        if old is not None:
            if p.channel and p.channel not in old.channels:
                old.channels.append(p.channel)
            if p.score <= old.score:
                return
            channels = old.channels
        else:
            channels = [p.channel] if p.channel else []
        tier = tier_of(key)
        bucket[key] = Evidence(
            idx=0,
            claim_idx=claim_idx,
            title=p.title.strip(),
            url=key,
            site=p.site or domain_of(p.url),
            date=p.date or "",
            date_parsed=parse_date(p.date),
            tier=tier,
            tier_name=tier_name(tier),
            score=p.score,
            snippet=p.snippet,
            channels=channels,
            is_debunk=is_debunk_site(p.url) or bool(_DEBUNK_TITLE_RE.search(p.title or "")),
        )

    def _deep_read(self, report: Report, items: list[Evidence], say) -> dict[int, str]:
        """每条主张取等级最高、分数最高的若干页抓原文，截取与主张关键词相关的片段。"""
        out: dict[int, str] = {}
        for ci, claim in enumerate(report.claims):
            kws = list(claim.entities) + re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", claim.queries.get("core", ""))
            # 数字类细节是摘要里最常缺的：年份、金额、人数、百分比、文号
            kws += re.findall(r"\d{4}年|\d+(?:\.\d+)?(?:万亿|亿|万)?(?:元|件|人|所|个|次|米|公里|基点)?|\d+(?:\.\d+)?%|〔\d{4}〕\d+号", claim.text)
            kws = [k for k in kws if not (k.isdigit() and len(k) <= 2)]
            picked = [e for e in items if e.claim_idx == ci and e.tier <= 3][: self.deep_read]
            if picked:
                say(f"主张 {ci + 1}：深读 {len(picked)} 篇原文…")
            for e in picked:
                text = fetch_text(e.url)
                if len(text) < 200:
                    continue
                ex = excerpt(text, kws)
                if ex:
                    out[e.idx] = ex
        self._deep_pages = len(out)
        return out

    def _judge(self, report: Report, items: list[Evidence], origin_candidates: list[Evidence] | None = None,
               deep: dict[int, str] | None = None) -> None:
        deep = deep or {}
        claims_txt = "\n".join(f"主张{i + 1}：{c.text}" for i, c in enumerate(report.claims))
        origin_candidates = origin_candidates or []
        # 溯源候选里不在 items 中的，也要给大模型看到摘要，否则无法判断是否在转述传闻
        extra = [e for e in origin_candidates if e not in items]
        lines = []
        for e in items + extra:
            d = e.date_parsed.isoformat() if e.date_parsed else "未知"
            flag = " | 辟谣平台/辟谣类内容" if e.is_debunk else ""
            snippet = re.sub(r"\s+", " ", e.snippet)[:SNIPPET_CHARS]
            lines.append(
                f"[{e.idx}] 主张{e.claim_idx + 1} | {e.tier_name} | {d} | {e.site or e.url} | {e.title}{flag}\n    {snippet}"
            )
            if e.idx in deep:
                lines.append("    【原文深读】" + deep[e.idx].replace("\n", "\n    "))
        if origin_candidates:
            cand = "\n".join(
                f"[{e.idx}] {e.date_parsed.isoformat()} | {e.tier_name} | {e.site or e.url} | {e.title}"
                for e in origin_candidates
            )
            origin = "按日期从早到晚的最早候选（编号与上面的证据一致）：\n" + cand
        else:
            origin = "无带日期的证据"
        user = (
            f"待核查传闻原文：\n{report.input_text[:1500]}\n\n"
            f"抽取的主张：\n{claims_txt}\n\n"
            f"检索到的证据（编号 | 对应主张 | 信源等级 | 日期 | 站点 | 标题，下一行为摘要）：\n" + "\n".join(lines) +
            f"\n\n溯源候选：\n{origin}"
        )
        system = """你是严谨的事实核查员。请仅依据用户给出的编号证据，判断传闻整体是否属实。

硬性规则：
1. 只能依据给定证据，不得使用证据以外的知识，不得编造证据、链接、日期或机构表态。
2. 没有与主张直接相关的证据时，必须输出「证据不足」。
3. 信源等级越靠前越可信：政府/官方 > 中央媒体 > 主流媒体 > 门户/垂直 > 自媒体/未知；辟谣平台的明确辟谣是强证据。
4. 只有转述传闻本身、而无权威确认的内容，不能作为「属实」的依据。
5. 「部分属实」只用于：有证据明确表明某条主张与事实不符（如数字、主体、时间被权威信源否定）。
6. 核心主张已被权威信源证实，其余只是细节（文号、附带数字、废止条款等）在摘要里没出现、但也没有任何证据与之矛盾时，应判「属实」，并在 reasoning 里说明哪些细节未能逐一核实、适当降低 confidence。
7. 某个表述同时出现在另一份文件或更早的报道里，不构成「本文件没有该表述」的证据；只有拿到本文件原文或官方解读明确不含该内容，才能据此否定。
8. 搜索摘要是节选，缺少某句话不等于原文没有这句话；带【原文深读】的证据附有抓取的原文片段，可信度高于摘要。
9. 传闻作为一个整体已被官方或辟谣平台明确辟谣（例如被定性为诈骗话术、编造信息）时，判「不实」，即使其中个别数字碰巧与真实政策一致。

输出 JSON 字段：
- verdict：属实 / 不实 / 部分属实 / 证据不足 四选一
- confidence：0~1 的小数
- reasoning：中文 2~5 句，每句末尾用 [编号] 引用支撑它的证据
- key_evidence：最关键的证据编号列表（整数，最多 5 个）
- official_stance：官方或权威媒体的口径，一两句话；没有则写"未检索到"
- origin_idx：溯源候选中「最早转述或报道这条传闻本身」的证据编号（整数）。注意区分：只是同一话题的背景报道、政策原文、或后来的辟谣文章都不算首发；没有合适的就填 null
- origin_note：关于首发来源的一句话。有 origin_idx 时说明它是检索范围内最早出现该传闻的内容及其信源性质；没有时说明检索范围内未找到传闻本身的早期版本，并指出最早的相关背景是什么"""
        try:
            data = self.llm.chat_json(system, user, max_tokens=1500)
        except Exception as e:  # noqa: BLE001
            report.warnings.append(f"判定失败：{e}")
            report.verdict, report.reasoning = "证据不足", "大模型判定失败，无法给出结论。"
            return

        verdict = str(data.get("verdict") or "").strip()
        if verdict not in VERDICTS:
            # 宽松映射，例如「基本属实」「不属实」
            verdict = next((v for v in ("部分属实", "不实", "证据不足", "属实") if v in verdict), "证据不足")
            if "不属实" in str(data.get("verdict")):
                verdict = "不实"
        report.verdict = verdict
        try:
            report.confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
        except (TypeError, ValueError):
            report.confidence = 0.0
        report.reasoning = str(data.get("reasoning") or "").strip()
        report.official_stance = str(data.get("official_stance") or "").strip() or "未检索到"
        if data.get("origin_note"):
            report.origin_note = str(data["origin_note"]).strip()
        by_idx = {e.idx: e for e in report.evidence}
        cand_idx = {e.idx for e in origin_candidates}
        oi = data.get("origin_idx")
        try:
            oi = int(str(oi).strip("[] ")) if oi not in (None, "", "null") else None
        except ValueError:
            oi = None
        if oi in cand_idx:
            report.origin = by_idx[oi]
            report.origin_kind = "rumor"
        else:
            report.origin_kind = "background"
        keys = []
        for k in data.get("key_evidence") or []:
            try:
                k = int(str(k).strip("[] "))
            except ValueError:
                continue
            if k in by_idx and by_idx[k] not in keys:
                keys.append(by_idx[k])
        report.key_evidence = keys

    def _extension_queries(self, report: Report) -> list[str]:
        ents = sorted({e for c in report.claims for e in c.entities})
        system = "你是资讯编辑。根据给定的话题和实体，给出 3 个读者可能还想了解的相关检索词（每个 4~15 字，不要与原话题重复）。输出 JSON：{\"queries\": [\"...\", \"...\", \"...\"]}"
        user = f"话题：{report.topic}\n实体：{'、'.join(ents) or '无'}\n传闻：{report.input_text[:300]}"
        try:
            data = self.llm.chat_json(system, user, temperature=0.5, max_tokens=300)
        except Exception as e:  # noqa: BLE001
            report.warnings.append(f"延伸话题生成失败：{e}")
            return []
        qs = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
        return qs[:3]
