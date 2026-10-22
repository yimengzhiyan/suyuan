"""OpenAI 兼容的大模型客户端（默认腾讯混元）。"""
from __future__ import annotations

import json
import os
import re

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.hunyuan.cloud.tencent.com/v1"
DEFAULT_MODEL = "hunyuan-turbos-latest"

JSON_INSTRUCTION = "\n\n只输出一个 JSON 对象，不要输出任何解释、前后缀或 Markdown 代码块标记。"


class LLMError(RuntimeError):
    pass


def parse_json_loose(text: str) -> dict:
    """稳健解析模型输出的 JSON：剥离 ```json 代码块，截取首尾花括号。"""
    if not text:
        raise LLMError("模型输出为空")
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S | re.I)
    if m:
        s = m.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"输出中没有 JSON 对象: {text[:200]}")
    s = s[start : end + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # 常见毛病：结尾多逗号
        s2 = re.sub(r",\s*([}\]])", r"\1", s)
        try:
            data = json.loads(s2)
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 解析失败: {e}; 原文: {text[:200]}") from e
    if not isinstance(data, dict):
        raise LLMError("JSON 顶层不是对象")
    return data


class LLM:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 60,
    ):
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
        if not self.api_key:
            raise LLMError("缺少 LLM_API_KEY，请在 .env 中配置")
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=timeout)
        self.calls = 0
        self.tokens = 0
        # Kimi Code（api.kimi.com/coding）是推理模型：默认开思考且温度只允许固定值。
        # 这里关闭思考、不传温度，输出更稳定也省 token。其他 OpenAI 兼容接口不受影响。
        self._kimi_code = "kimi.com" in self.base_url
        # 关闭思考模式：Kimi Code 默认关；其他接口（如开放平台的 kimi-k2.6 / kimi-k3）用 LLM_THINKING=off 显式关闭
        thinking_off = self._kimi_code or os.getenv("LLM_THINKING", "").lower() in ("off", "0", "false", "disabled")
        self._extra_body = {"thinking": {"type": "disabled"}} if thinking_off else None

    def chat(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2000) -> str:
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        if not self._kimi_code:
            kwargs["temperature"] = temperature
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        resp = self.client.chat.completions.create(**kwargs)
        self.calls += 1
        if resp.usage:
            self.tokens += resp.usage.total_tokens or 0
        return (resp.choices[0].message.content or "").strip()

    def chat_json(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2000) -> dict:
        text = self.chat(system + JSON_INSTRUCTION, user, temperature=temperature, max_tokens=max_tokens)
        try:
            return parse_json_loose(text)
        except LLMError:
            # 模型偶尔输出残缺 JSON（如把一段文字拆成两个字符串）；让它自己修一次
            fixed = self.chat(
                "你是 JSON 修复器。用户给你一段有语法错误的 JSON，请在不改变字段含义的前提下修复，只输出修复后的 JSON。",
                text, temperature=0.0, max_tokens=max_tokens,
            )
            return parse_json_loose(fixed)
