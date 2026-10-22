"""把 Report 渲染成 Markdown 核查卡。"""
from __future__ import annotations

from .verify import Report

VERDICT_ICON = {"属实": "🟢", "不实": "🔴", "部分属实": "🟠", "证据不足": "⚪"}
CHANNEL_NAMES = {
    "mixed": "混合",
    "news": "新闻",
    "gov": "政务",
    "debunk": "辟谣词",
    "debunk_site": "辟谣平台",
    "origin_probe": "溯源补搜",
    "extend": "延伸",
}


def _cell(s: str, n: int = 60) -> str:
    """表格单元格：去换行、转义竖线、截断。"""
    s = (s or "").replace("\n", " ").replace("|", "\\|").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def render_markdown(report: Report, max_rows: int = 30) -> str:
    r = report
    out: list[str] = []
    out.append(f"# 溯源核查卡：{r.topic or '未命名'}")
    out.append("")
    out.append(f"> {_cell(r.input_text, 200)}")
    out.append("")
    out.append(f"## 判定：{VERDICT_ICON.get(r.verdict, '')} {r.verdict}（置信度 {r.confidence:.0%}）")
    out.append("")

    if r.claims:
        out.append("**核查的主张**")
        out.append("")
        for i, c in enumerate(r.claims, 1):
            out.append(f"{i}. {c.text}  （检索词：`{c.queries.get('core', '')}`）")
        out.append("")

    out.append("## 结论与依据")
    out.append("")
    out.append(r.reasoning or "无")
    if r.key_evidence:
        out.append("")
        out.append("**关键证据**")
        out.append("")
        for e in r.key_evidence:
            d = e.date_parsed.isoformat() if e.date_parsed else "日期未知"
            out.append(f"- [{e.idx}] {e.tier_name} · {d} · {e.site} · [{_cell(e.title, 80)}]({e.url})")
    out.append("")

    out.append("## 官方口径")
    out.append("")
    out.append(r.official_stance or "未检索到")
    out.append("")

    out.append("## 首发来源")
    out.append("")
    if r.origin:
        o = r.origin
        label = "传闻首发（检索可见范围内最早转述该传闻）" if getattr(report, "origin_kind", "") == "rumor" else "最早相关内容（未找到传闻本身的早期版本）"
        out.append(f"- {label}：{o.date_parsed} · {o.site}（{o.tier_name}）· [{_cell(o.title, 80)}]({o.url})")
    if r.origin_note:
        out.append(f"- {r.origin_note}")
    if not r.origin and not r.origin_note:
        out.append("未找到带日期的相关内容。")
    out.append("")

    out.append(f"## 证据（共 {len(r.evidence)} 条）")
    out.append("")
    if r.evidence:
        out.append("| 编号 | 等级 | 日期 | 站点 | 标题 | 来路 |")
        out.append("|---|---|---|---|---|---|")
        for e in r.evidence[:max_rows]:
            d = e.date_parsed.isoformat() if e.date_parsed else ""
            title = f"[{_cell(e.title, 50) or e.url}]({e.url})"
            via = "、".join(CHANNEL_NAMES.get(c, c) for c in e.channels)
            if e.is_debunk:
                via += " ⚑辟谣"
            out.append(f"| {e.idx} | {e.tier_name} | {d} | {_cell(e.site, 25)} | {title} | {via} |")
        if len(r.evidence) > max_rows:
            out.append(f"\n（其余 {len(r.evidence) - max_rows} 条见 JSON 输出）")
    else:
        out.append("未检索到证据。")
    out.append("")

    out.append("## 时间线")
    out.append("")
    if r.timeline:
        for t in r.timeline[:20]:
            out.append(f"- {t.date.isoformat()} · {t.site}（T{t.tier}）· [{_cell(t.title, 60)}]({t.url})")
        if len(r.timeline) > 20:
            out.append(f"- …（共 {len(r.timeline)} 条）")
    else:
        out.append("无带日期的证据。")
    out.append("")

    if r.extensions:
        out.append("## 延伸话题")
        out.append("")
        for x in r.extensions:
            out.append(f"**{x.query}**")
            out.append("")
            for it in x.items:
                out.append(f"- [{_cell(it.get('title', ''), 60)}]({it.get('url', '')}) · {it.get('site', '')} {it.get('date', '')}")
            if not x.items:
                out.append("- 无结果")
            out.append("")

    s = r.stats or {}
    out.append("## 统计")
    out.append("")
    out.append(
        f"搜索调用 {s.get('search_calls', 0)} 次（缓存命中 {s.get('cached_hits', 0)}）· "
        f"大模型调用 {s.get('llm_calls', 0)} 次（{s.get('llm_tokens', 0)} tokens）· "
        f"证据 {s.get('evidence_count', 0)} 条 · 耗时 {s.get('elapsed', 0)} 秒"
    )
    dist = s.get("tier_distribution")
    if dist:
        out.append("")
        out.append("信源分布：" + "，".join(f"{k} {v}" for k, v in dist.items()))
    if r.warnings:
        out.append("")
        out.append("**警告**")
        out.append("")
        out += [f"- {w}" for w in r.warnings]
    out.append("")
    return "\n".join(out)
