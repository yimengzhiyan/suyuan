"""截图文字识别：本地 RapidOCR（onnxruntime，CPU），不依赖访问者的大模型。"""
from __future__ import annotations

import io
import threading
import time

from PIL import Image, ImageOps

MAX_SIDE = 1600
_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def recognize(data: bytes) -> dict:
    """返回 {"text": 合并文本, "lines": [...], "elapsed": 秒}。"""
    t0 = time.time()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        r = MAX_SIDE / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    import numpy as np

    arr = np.asarray(img)[:, :, ::-1]  # RapidOCR 期望 BGR
    res, _ = _get_engine()(arr)
    items = []
    for item in res or []:
        box, text, score = item[0], str(item[1]).strip(), float(item[2])
        if text and score >= 0.5:
            ys = [pt[1] for pt in box]
            xs = [pt[0] for pt in box]
            items.append({"text": text, "top": min(ys), "bottom": max(ys), "left": min(xs)})
    items.sort(key=lambda d: (d["top"], d["left"]))
    lines = [d["text"] for d in items]
    text = _join(items)
    return {"text": text, "lines": lines, "elapsed": round(time.time() - t0, 2)}


def _join(items: list[dict]) -> str:
    """把 OCR 的逐行结果拼成段落。

    聊天截图里一个气泡是一段。两行之间的垂直间距明显大于行高（换了气泡或换了段）就换行，
    否则直接接上；上一行以句末标点结束时也换行。
    """
    out = ""
    prev = None
    for d in items:
        if prev is None:
            out = d["text"]
        else:
            line_h = max(prev["bottom"] - prev["top"], 1)
            gap = d["top"] - prev["bottom"]
            new_para = gap > 0.8 * line_h or out[-1] in "。！？!?；;…"
            out += ("\n" if new_para else "") + d["text"]
        prev = d
    return out
