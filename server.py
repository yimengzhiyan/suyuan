"""新版网页的后端：FastAPI + SSE。

    .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8601

接口：
  GET  /                 新版前端（web/index.html）
  GET  /api/examples     示例传闻
  POST /api/verify       SSE 流：progress → result | error
       body: {"text", "wsa_key", "llm_base_url", "llm_api_key", "llm_model", "thinking_off", "use_cache"}
公开模式（SUYUAN_PUBLIC=1）下不使用服务器 .env 里的 key，访问者必须自带。
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import suyuan  # noqa: F401  触发 load_dotenv
from suyuan.llm import LLM
from suyuan.report import render_markdown
from suyuan.search import YuanbaoSearch
from suyuan.verify import Verifier

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
PUBLIC_MODE = os.getenv("SUYUAN_PUBLIC", "").lower() in ("1", "true", "yes")
MAX_CONCURRENT = int(os.getenv("SUYUAN_MAX_CONCURRENT", "4"))
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

EXAMPLES = [
    {"label": "医保清零", "text": "网传：国家卫健委宣布从2026年1月1日起全面取消医保个人账户，所有余额清零。"},
    {"label": "高速免费取消", "text": "网传：2025年起全国取消高速公路节假日免费通行政策，交通部已下发文件。"},
    {"label": "医院取消值班", "text": "网传：5月1日起全国二级及以上公立医院取消24小时值班，医生不用值夜班了。"},
]

# 进度文案 → 链条步骤 id，前端据此点亮对应节点
STEP_PATTERNS = [
    (re.compile(r"^抽取可核实主张"), "claims"),
    (re.compile(r"^主张 \d+：.*检索"), "search"),
    (re.compile(r"^构建溯源时间线|^溯源补搜"), "timeline"),
    (re.compile(r"^主张 \d+：深读"), "deepread"),
    (re.compile(r"^大模型基于"), "judge"),
    (re.compile(r"^生成延伸话题"), "extend"),
    (re.compile(r"^完成"), "done"),
]


def step_of(msg: str) -> str | None:
    for pat, step in STEP_PATTERNS:
        if pat.search(msg):
            return step
    return None


class VerifyBody(BaseModel):
    text: str = Field(..., min_length=2, max_length=1500)
    wsa_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    thinking_off: bool = False
    use_cache: bool = True


app = FastAPI(title="溯源", docs_url=None, redoc_url=None)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/examples")
def examples():
    return EXAMPLES


@app.get("/api/config")
def config():
    return {"public": PUBLIC_MODE, "server_search_key": (not PUBLIC_MODE) and bool(os.getenv("TENCENTCLOUD_WSA_APIKEY")),
            "server_llm_key": (not PUBLIC_MODE) and bool(os.getenv("LLM_API_KEY"))}


@app.post("/api/verify")
def verify(body: VerifyBody, request: Request):
    wsa_key = body.wsa_key.strip() or ("" if PUBLIC_MODE else os.getenv("TENCENTCLOUD_WSA_APIKEY", ""))
    llm_key = body.llm_api_key.strip() or ("" if PUBLIC_MODE else os.getenv("LLM_API_KEY", ""))
    if not wsa_key:
        return JSONResponse({"error": "缺少元宝搜索 API Key"}, status_code=400)
    if not _slots.acquire(blocking=False):
        return JSONResponse({"error": "服务器正忙，请稍后再试"}, status_code=429)

    q: queue.Queue = queue.Queue()

    def work():
        try:
            search = YuanbaoSearch(api_key=wsa_key, use_cache=body.use_cache)
            llm = None
            if llm_key:
                llm = LLM(base_url=body.llm_base_url.strip() or None, api_key=llm_key,
                          model=body.llm_model.strip() or None, thinking_off=body.thinking_off)

            def progress(msg: str):
                q.put(("progress", {"msg": msg, "step": step_of(msg)}))

            report = Verifier(search, llm).verify(body.text.strip(), progress=progress)
            data = report.to_dict()
            data["markdown"] = render_markdown(report)
            q.put(("result", data))
        except Exception as e:  # noqa: BLE001
            q.put(("error", {"error": str(e)}))
        finally:
            _slots.release()
            q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        yield sse("progress", {"msg": "开始核查", "step": "start"})
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            yield sse(*item)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if WEB.exists():
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
def index():
    f = WEB / "index.html"
    if f.exists():
        return FileResponse(str(f))
    return JSONResponse({"message": "前端尚未构建，接口可用：POST /api/verify"})
