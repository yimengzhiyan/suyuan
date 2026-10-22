"""原文深读：抓取少量高等级证据页面的正文，截取与主张相关的片段。

搜索摘要只是节选，常常缺少文号、废止条款、具体数字等细节；判定时补上原文片段能明显减少
「细节未核实」导致的误判。只抓 tier 较高的少量页面，失败就跳过，并做磁盘缓存。
"""
from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CACHE_DIR = Path(os.getenv("SUYUAN_CACHE_DIR", ".cache")) / "pages"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", re.S | re.I)
_BLOCK_RE = re.compile(r"</?(p|div|br|li|tr|h\d|section|article)[^>]*>", re.I)


def fetch_text(url: str, timeout: int = 8, max_chars: int = 20000) -> str:
    """抓取网页并转成纯文本；任何失败都返回空串。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".txt")
    if f.exists():
        return f.read_text("utf-8")
    text = ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, verify=False)
        if r.ok and "html" in r.headers.get("content-type", "html").lower():
            raw = r.content
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            for e in (enc, "utf-8", "gb18030"):
                if not e:
                    continue
                try:
                    s = raw.decode(e)
                    break
                except (UnicodeDecodeError, LookupError):
                    s = ""
            if s:
                s = _TAG_RE.sub(" ", s)
                s = _BLOCK_RE.sub("\n", s)
                s = re.sub(r"<[^>]+>", " ", s)
                s = html_lib.unescape(s)
                s = re.sub(r"[ \t\r\f\v]+", " ", s)
                s = re.sub(r"\n\s*\n+", "\n", s).strip()
                text = s[:max_chars]
    except Exception:  # noqa: BLE001
        text = ""
    f.write_text(text, "utf-8")
    return text


def excerpt(text: str, keywords: list[str], window: int = 220, max_total: int = 900) -> str:
    """围绕关键词命中处截取片段，合并重叠，总长不超过 max_total。"""
    if not text:
        return ""
    kws = [k for k in {k.strip() for k in keywords} if len(k) >= 2]
    spans: list[tuple[int, int]] = []
    for k in kws:
        for m in re.finditer(re.escape(k), text):
            spans.append((max(0, m.start() - window // 2), min(len(text), m.end() + window // 2)))
            if len(spans) > 40:
                break
    if not spans:
        return text[:max_total]
    spans.sort()
    merged = [spans[0]]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    out, total = [], 0
    for a, b in merged:
        piece = text[a:b].strip()
        if total + len(piece) > max_total:
            piece = piece[: max_total - total]
        out.append("…" + piece + "…")
        total += len(piece)
        if total >= max_total:
            break
    return "\n".join(out)
