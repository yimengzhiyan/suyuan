"""Streamlit 页面：streamlit run app.py"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import streamlit as st

import suyuan  # noqa: F401 —— 触发 load_dotenv
from suyuan import ui
from suyuan.llm import DEFAULT_BASE_URL, DEFAULT_MODEL, LLM
from suyuan.report import CHANNEL_NAMES, render_markdown
from suyuan.search import YuanbaoSearch
from suyuan.sources import TIER_NAMES
from suyuan.verify import Report, Verifier

ROOT = Path(__file__).resolve().parent
TIMELINE_SHOW = 25
EXAMPLES = [
    ("医保个人账户清零？", "网传：国家卫健委宣布从2026年1月1日起全面取消医保个人账户，所有余额清零。"),
    ("高速节假日免费取消？", "网传：2025年起全国取消高速公路节假日免费通行政策，交通部已下发文件。"),
    ("医院取消24小时值班？", "网传：5月1日起全国二级及以上公立医院取消24小时值班，医生不用值夜班了。"),
]

st.set_page_config(page_title="溯源 · 传闻求证", page_icon="🔎", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


# ---- 侧栏：配置状态 --------------------------------------------------------
search_key_ok = bool(os.getenv("TENCENTCLOUD_WSA_APIKEY"))
llm_key_ok = bool(os.getenv("LLM_API_KEY"))
with st.sidebar:
    st.subheader("配置")
    use_cache = st.toggle("搜索缓存", value=True, help="相同查询读本地缓存，不重复消耗额度")
    no_llm = st.toggle("仅检索", value=not llm_key_ok, help="不调用大模型，判定固定为「证据不足」")
    st.caption(f"元宝搜索：{'✅ 已配置' if search_key_ok else '❌ 未配置'}")
    st.caption(f"大模型：{'✅ 已配置' if llm_key_ok else '❌ 未配置'} · {os.getenv('LLM_MODEL') or DEFAULT_MODEL}")
    st.caption(f"接口：{os.getenv('LLM_BASE_URL') or DEFAULT_BASE_URL}")

html(ui.header_html())

tab_check, tab_how, tab_about = st.tabs(["核查", "工作原理", "关于"])


# ---- 结果展示 --------------------------------------------------------------
def show_report(r: Report) -> None:
    # a. 判定卡
    html(ui.verdict_card(r))

    # b. 结论与依据
    html(ui.section("结论与依据"))
    html(ui.text_box(r.reasoning))
    if r.key_evidence:
        st.markdown("**关键证据**")
        html(ui.evidence_list(r.key_evidence))

    # c. 官方口径 / 首发来源
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        html(ui.section("官方口径"))
        html(ui.text_box(r.official_stance or "未检索到"))
    with c2:
        html(ui.section("首发来源"))
        html(ui.origin_html(r))

    # d. 传播时间线
    html(ui.section(f"传播时间线（{len(r.timeline)} 条）"))
    if r.timeline:
        origin_url = r.origin.url if r.origin else ""
        html(ui.timeline_html(r.timeline[:TIMELINE_SHOW], TIER_NAMES, origin_url))
        if len(r.timeline) > TIMELINE_SHOW:
            shown = {t.url for t in r.timeline[:TIMELINE_SHOW]}
            rest_origin = "" if origin_url in shown else origin_url
            with st.expander(f"其余 {len(r.timeline) - TIMELINE_SHOW} 条"):
                html(ui.timeline_html(r.timeline[TIMELINE_SHOW:], TIER_NAMES, rest_origin))
    else:
        st.caption("无带日期的证据")

    # e. 全部证据
    html(ui.section("全部证据"))
    with st.expander(f"证据表（{len(r.evidence)} 条）", expanded=True):
        if r.evidence:
            rows = [
                {
                    "编号": e.idx,
                    "等级": e.tier_name,
                    "日期": e.date_parsed.isoformat() if e.date_parsed else "",
                    "站点": e.site,
                    "标题": e.title,
                    "链接": e.url,
                    "来路": "、".join(CHANNEL_NAMES.get(c, c) for c in e.channels),
                    "辟谣": "是" if e.is_debunk else "",
                }
                for e in r.evidence
            ]
            st.dataframe(rows, width="stretch", hide_index=True,
                         column_config={"链接": st.column_config.LinkColumn("链接", display_text="打开")})
        else:
            st.caption("未检索到证据")

    # f. 延伸话题
    if r.extensions:
        html(ui.section("延伸话题"))
        cols = st.columns(len(r.extensions), gap="small")
        for col, x in zip(cols, r.extensions):
            with col:
                html(ui.extension_card(x))

    # g. 本次开销
    s = r.stats or {}
    html(ui.section("本次开销"))
    m = st.columns(4)
    m[0].metric("搜索调用", s.get("search_calls", 0), help=f"缓存命中 {s.get('cached_hits', 0)} 次", border=True)
    m[1].metric("大模型调用", s.get("llm_calls", 0), border=True)
    m[2].metric("证据条数", s.get("evidence_count", len(r.evidence)), border=True)
    m[3].metric("耗时（秒）", s.get("elapsed", 0), border=True)
    st.caption(f"深读原文 {s.get('deep_read_pages', 0)} 篇 · 缓存命中 {s.get('cached_hits', 0)} 次")
    for w in r.warnings:
        st.warning(w)

    # h. 下载
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button("下载核查卡 Markdown", render_markdown(r), file_name="suyuan_report.md", width="stretch")
    d2.download_button("下载 JSON", json.dumps(r.to_dict(), ensure_ascii=False, indent=2),
                       file_name="suyuan_report.json", width="stretch")


def _fill(example: str) -> None:
    st.session_state["rumor_text"] = example


# ---- Tab 1：核查 -----------------------------------------------------------
with tab_check:
    if not search_key_ok:
        st.error("未检测到 TENCENTCLOUD_WSA_APIKEY。请复制 `.env.example` 为 `.env` 并填写元宝搜索 API Key 后重启。")
    if not llm_key_ok:
        st.warning("未检测到 LLM_API_KEY：只能使用「仅检索」模式，判定结果固定为「证据不足」。")

    text = st.text_area("粘贴传闻正文", key="rumor_text", height=120,
                        placeholder="把在群聊、朋友圈、短视频里看到的说法粘贴到这里（请粘贴正文，本工具不抓取链接内容）")
    row = st.columns([1, 1, 1, 1.2], vertical_alignment="center")
    for col, (label, ex) in zip(row[:3], EXAMPLES):
        col.button(f"示例：{label}", on_click=_fill, args=(ex,), width="stretch", help=ex)
    go = row[3].button("开始核查", type="primary", disabled=not search_key_ok, width="stretch")

    if go:
        text = (text or "").strip()
        if not text:
            st.warning("请先粘贴传闻内容")
        else:
            if re.fullmatch(r"https?://\S+", text):
                st.warning("只粘贴了链接：本工具不抓取网页，将仅以链接文本检索，建议粘贴正文。")
            try:
                search = YuanbaoSearch(use_cache=use_cache)
                llm = None if no_llm else LLM()
            except Exception as e:  # noqa: BLE001
                st.error(f"初始化失败：{e}")
                st.stop()
            with st.status("核查中…", expanded=True) as status:
                report = Verifier(search, llm).verify(text, progress=st.write)
                status.update(label=f"核查完成：{report.verdict}", state="complete", expanded=False)
            st.session_state["report"] = report
    if "report" in st.session_state:
        show_report(st.session_state["report"])
    elif not go:
        st.info("粘贴一段传闻，或点一个示例，然后点「开始核查」。")


# ---- Tab 2：工作原理 -------------------------------------------------------
with tab_how:
    svg_path = ROOT / "article" / "architecture.svg"
    if svg_path.exists():
        st.image(svg_path.read_text(encoding="utf-8"), width="stretch")
    else:
        st.caption("未找到 article/architecture.svg")
    st.markdown(
        """
**① 主张抽取。** 大模型把一段传闻拆成最多 3 条可公开核实的原子主张，并为每条生成核心检索词和辟谣检索词；大模型不可用时用规则兜底。

**② 多路检索与信源分级。** 每条主张调用元宝搜索 API 走五路：混合信源、新闻行业、政务行业、辟谣关键词，以及对中国互联网联合辟谣平台、腾讯较真的站内定向检索。结果按 URL 去重，再用域名白名单分成五档信源（政府/官方 → 自媒体/未知）。

**③ 溯源时间线。** 把带日期的证据按时间排序，取最早一条，在它之前 30 天的窗口内再补搜一次，由大模型从最早的候选里挑出「传闻首发」；找不到传闻本身时，明确标注为「最早相关背景」。

**④ 有据判定。** 判定前先深读几篇高等级信源的原文，大模型只依据编号证据输出属实 / 不实 / 部分属实 / 证据不足，每句结论带 `[编号]` 引用；检索不到就判「证据不足」。最后再生成 3 个延伸话题检索，供读者继续了解。
"""
    )


# ---- Tab 3：关于 -----------------------------------------------------------
with tab_about:
    _poster = ROOT / "article" / "poster.png"
    if _poster.exists():
        _c1, _c2, _c3 = st.columns([1, 2, 1])
        with _c2:
            st.image(str(_poster), use_container_width=True)
    st.markdown(
        """
#### 项目说明
「溯源」是一个基于腾讯元宝搜索 API 的网络传闻求证与溯源工具。把在群聊、朋友圈里看到的传闻粘贴进来，它会拆出可核实的主张、多路检索、按信源等级排序、排出传播时间线并尽量找到首发来源，最后只依据编号证据给出判定，每句结论都可以点回原文。

#### 技术栈
- 检索：腾讯元宝搜索 API（个人版），带本地磁盘缓存
- 大模型：任意 OpenAI 兼容接口，默认腾讯混元 `hunyuan-turbos-latest`
- 界面：Streamlit；另有命令行 `cli.py` 与评测脚本 `eval/run_eval.py`
- 语言：Python 3.11

#### 已知限制
- 个人版接口没有 `authority_level`（权威度）字段，所以自建了域名白名单做五档信源分级；未收录的地方媒体、官方机构自建域名会被归为「自媒体/未知」，微信公众号无法区分官方号与个人号。
- 「首发来源」只是**搜索引擎可见范围内**日期最早的相关内容，并非真正的首发；日期格式不统一，解析失败的证据不进入时间线。
- 判定质量取决于检索召回与大模型能力：检索不到时会输出「证据不足」，这是有意为之。
- 判定前只深读等级最高的少量证据原文；输入处不抓取网页，粘贴链接时只能以链接文本检索，请粘贴传闻正文。
- 每次核查约 8～16 次检索（按主张数）外加 3 次延伸检索，默认开启本地缓存以节省额度。

"""
    )
