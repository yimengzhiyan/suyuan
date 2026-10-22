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
    lines: list[str] = []
    for item in res or []:
        box, text, score = item[0], str(item[1]).strip(), float(item[2])
        if text and score >= 0.5:
            lines.append(text)
    text = _join(lines)
    return {"text": text, "lines": lines, "elapsed": round(time.time() - t0, 2)}


def _join(lines: list[str]) -> str:
    """把 OCR 的逐行结果拼成段落：上一行不以句末标点结束就直接接上。"""
    out = ""
    for ln in lines:
        if not out:
            out = ln
        elif out[-1] in "。！？!?；;…":
            out += "\n" + ln
        else:
            out += ln
    return out
