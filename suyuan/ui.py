"""Streamlit 页面的纯展示辅助：生成内联 HTML 片段与样式，不含任何业务逻辑。"""
from __future__ import annotations

import html
from datetime import date

VERDICT_COLORS = {"属实": "#2e7d32", "不实": "#c62828", "部分属实": "#ef6c00", "证据不足": "#757575"}

# 五档信源徽章：(背景色, 文字色)
TIER_BADGE = {
    1: ("#0d3b66", "#ffffff"),  # 政府/官方 深蓝
    2: ("#1e6fd9", "#ffffff"),  # 中央媒体 蓝
    3: ("#0f8b8d", "#ffffff"),  # 主流媒体 青
    4: ("#8a939c", "#ffffff"),  # 门户/垂直 灰
    5: ("#e3e6ea", "#4a5560"),  # 自媒体/未知 浅灰
}

CSS = """
<style>
.block-container{max-width:1200px;padding-top:2.2rem}
.sy-head{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px;
  border-bottom:1px solid #e6e8eb;padding-bottom:12px;margin-bottom:6px}
.sy-head h1{font-size:2.4rem;margin:0;padding:0;line-height:1.1;color:#1f2d3a}
.sy-head .sub{font-size:1.05rem;color:#4a5a68;margin-top:6px}
.sy-head .meta{font-size:.85rem;color:#7a8a98}
.sy-badge{display:inline-block;padding:1px 8px;border-radius:9px;font-size:.75rem;line-height:1.6;
  white-space:nowrap;vertical-align:middle}
.sy-card{border:1px solid #e6e8eb;border-left-width:8px;border-radius:8px;background:#fff;
  padding:18px 22px;margin:8px 0 16px}
.sy-verdict{font-size:2rem;font-weight:700;line-height:1.2}
.sy-conf{color:#5f6b76;font-size:.95rem;margin-left:12px}
.sy-topic{font-size:1.1rem;color:#1f2d3a;margin:8px 0 10px}
.sy-claims{margin:0;padding:0;list-style:none;border-top:1px dashed #e0e3e7;padding-top:8px}
.sy-claims li{margin:6px 0;color:#2b3a47}
.sy-claims .n{display:inline-block;width:1.6em;height:1.6em;line-height:1.6em;text-align:center;border-radius:50%;
  background:#f0f2f4;color:#4a5a68;font-size:.8rem;margin-right:8px}
.sy-claims .q{display:block;margin-left:2.3em;color:#8a96a1;font-size:.8rem}
.sy-sec{font-size:1.15rem;font-weight:700;color:#1f2d3a;margin:22px 0 8px;padding-left:10px;border-left:4px solid #1f2d3a}
.sy-box{background:#fafbfc;border:1px solid #eceef0;border-radius:8px;padding:14px 18px;color:#2b3a47;line-height:1.75}
.sy-ev{margin:0;padding:0;list-style:none}
.sy-ev li{padding:7px 0;border-bottom:1px solid #f0f2f4;line-height:1.6}
.sy-ev .idx{font-weight:700;color:#1f2d3a;margin-right:6px}
.sy-muted{color:#7a8a98;font-size:.85rem}
.sy-ev a,.sy-tl a,.sy-box a{color:#1a56a8;text-decoration:none}
.sy-tl{position:relative;margin:4px 0 0 8px;padding-left:22px;border-left:2px solid #d5dae0}
.sy-tl .it{position:relative;padding:4px 10px 10px;margin-bottom:4px;border-radius:6px}
.sy-tl .dot{position:absolute;left:-29px;top:9px;width:12px;height:12px;border-radius:50%;
  background:#fff;border:2px solid #8a96a1}
.sy-tl .it.first{background:#fff7e6;border:1px solid #f3d9a4}
.sy-tl .it.first .dot{background:#ef6c00;border-color:#ef6c00}
.sy-tl .d{font-weight:700;color:#1f2d3a;margin-right:8px}
.sy-tl .tag{background:#ef6c00;color:#fff;border-radius:4px;padding:0 6px;font-size:.75rem;margin-left:6px}
.sy-tl .t{display:block;margin-top:2px}
.sy-ext{border:1px solid #e6e8eb;border-radius:8px;padding:12px 14px;background:#fff;height:100%}
.sy-ext .q{font-weight:700;color:#1f2d3a;margin-bottom:6px}
.sy-ext ul{margin:0;padding-left:1.1em}
.sy-ext li{margin:4px 0;font-size:.9rem}
.sy-ext a{color:#1a56a8;text-decoration:none}
</style>
"""


def esc(s) -> str:
    """HTML 转义，并转义 $ 以免被 st.markdown 当成公式。"""
    return html.escape(str(s or "")).replace("$", "&#36;")


def link(title: str, url: str) -> str:
    return f'<a href="{esc(url)}" target="_blank">{esc(title or url)}</a>'


def fmt_date(d: date | None) -> str:
    return d.isoformat() if d else "日期未知"


def tier_badge(tier: int, name: str) -> str:
    bg, fg = TIER_BADGE.get(tier, TIER_BADGE[5])
    return f'<span class="sy-badge" style="background:{bg};color:{fg}">{esc(name)}</span>'


def header_html() -> str:
    return (
        '<div class="sy-head"><div><h1>溯源</h1><div class="sub">转发之前，先看看它从哪来</div></div>'
        '<div class="meta">基于元宝搜索 API · 多路检索 → 信源分级 → 溯源时间线 → 有据判定</div></div>'
    )


def section(title: str) -> str:
    return f'<div class="sy-sec">{esc(title)}</div>'


def verdict_card(r) -> str:
    color = VERDICT_COLORS.get(r.verdict, "#757575")
    claims = "".join(
        f'<li><span class="n">{i}</span>{esc(c.text)}'
        f'<span class="q">检索词：{esc(c.queries.get("core", ""))}</span></li>'
        for i, c in enumerate(r.claims, 1)
    )
    claims_html = f'<ul class="sy-claims">{claims}</ul>' if claims else ""
    return (
        f'<div class="sy-card" style="border-left-color:{color}">'
        f'<div><span class="sy-verdict" style="color:{color}">{esc(r.verdict)}</span>'
        f'<span class="sy-conf">置信度 {r.confidence:.0%}</span></div>'
        f'<div class="sy-topic">{esc(r.topic)}</div>{claims_html}</div>'
    )


def text_box(text: str) -> str:
    body = esc(text or "无").replace("\n", "<br>")
    return f'<div class="sy-box">{body}</div>'


def evidence_list(items) -> str:
    lis = "".join(
        f'<li><span class="idx">[{e.idx}]</span>{tier_badge(e.tier, e.tier_name)} '
        f'<span class="sy-muted">{fmt_date(e.date_parsed)} · {esc(e.site)}</span><br>{link(e.title, e.url)}</li>'
        for e in items
    )
    return f'<ul class="sy-ev">{lis}</ul>'


def origin_html(r) -> str:
    if not r.origin:
        return f'<div class="sy-box"><span class="sy-muted">{esc(r.origin_note or "未找到带日期的相关内容")}</span></div>'
    o = r.origin
    kind = "🧭 传闻首发" if getattr(r, "origin_kind", "") == "rumor" else "📚 最早相关背景（未找到传闻本身的早期版本）"
    note = f'<div class="sy-muted" style="margin-top:8px">{esc(r.origin_note)}</div>' if r.origin_note else ""
    return (
        f'<div class="sy-box"><div style="font-weight:700;margin-bottom:6px">{kind}</div>'
        f'<div><b>{fmt_date(o.date_parsed)}</b> · {esc(o.site)} {tier_badge(o.tier, o.tier_name)}</div>'
        f'<div>{link(o.title, o.url)}</div>{note}</div>'
    )


def timeline_html(items, tier_names: dict, origin_url: str = "") -> str:
    out = []
    marked = False
    for t in items:
        first = bool(origin_url) and not marked and t.url == origin_url
        marked = marked or first
        tag = '<span class="tag">首发</span>' if first else ""
        out.append(
            f'<div class="it{" first" if first else ""}"><span class="dot"></span>'
            f'<span class="d">{t.date.isoformat()}</span>{tier_badge(t.tier, tier_names.get(t.tier, ""))} '
            f'<span class="sy-muted">{esc(t.site)}</span>{tag}'
            f'<span class="t">{link(t.title, t.url)}</span></div>'
        )
    return f'<div class="sy-tl">{"".join(out)}</div>'


def extension_card(x) -> str:
    lis = "".join(f"<li>{link(it.get('title', ''), it.get('url', ''))}</li>" for it in x.items[:3])
    body = f"<ul>{lis}</ul>" if lis else '<span class="sy-muted">无结果</span>'
    return f'<div class="sy-ext"><div class="q">🔍 {esc(x.query)}</div>{body}</div>'
