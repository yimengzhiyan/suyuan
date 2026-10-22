"""元宝搜索 SearchPro 客户端。

- API Key 走 Bearer 鉴权，域名 api.wsa.cloud.tencent.com
- Pages 里每一项是 JSON 字符串，这里统一解析成 dict
- 带本地磁盘缓存：相同参数不重复扣额度，评测可复现
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import requests

ENDPOINT = "https://api.wsa.cloud.tencent.com/SearchPro"
TC3_HOST = "wsa.tencentcloudapi.com"
TC3_SERVICE = "wsa"
TC3_ACTION = "SearchPro"
TC3_VERSION = "2025-05-08"
CACHE_DIR = Path(os.getenv("SUYUAN_CACHE_DIR", ".cache/search"))


class SearchError(RuntimeError):
    pass


@dataclass
class Page:
    title: str = ""
    url: str = ""
    site: str = ""
    date: str = ""
    passage: str = ""
    content: str = ""
    score: float = 0.0
    authority_level: int | None = None
    favicon: str = ""
    pics: list = field(default_factory=list)
    deeplinks: list = field(default_factory=list)
    # 由本项目补充的字段
    query: str = ""
    channel: str = ""  # 来自哪一路检索，如 mixed / news / gov / debunk

    @classmethod
    def from_raw(cls, raw: Any, query: str = "", channel: str = "") -> "Page":
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {"passage": raw}
        known = {k: raw.get(k) for k in cls.__dataclass_fields__ if k in raw}
        p = cls(**{k: v for k, v in known.items() if v is not None})
        try:
            p.score = float(p.score or 0)
        except (TypeError, ValueError):
            p.score = 0.0
        p.query, p.channel = query, channel
        return p

    @property
    def snippet(self) -> str:
        return (self.content or self.passage or "").strip()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    query: str
    params: dict
    pages: list[Page]
    version: str = ""
    msg: str = ""
    request_id: str = ""
    cached: bool = False
    elapsed: float = 0.0


class YuanbaoSearch:
    """元宝搜索客户端。

    参数含义（见腾讯云文档 1806/121811）：
      mode:      0 公开网页；1 优质权威垂直信源；2 混合。极速版不支持
      site:      "example.com" 只搜该域名；"exclude:a.com|b.com" 排除，最多 5 个
      cnt:       10/20/30/40/50
      industry:  gov / news / acad / finance
      freshness: dN / mN / yN / yyyy-mm-dd / "yyyy-mm-dd,yyyy-mm-dd"
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_id: str | None = None,
        secret_key: str | None = None,
        use_cache: bool = True,
        timeout: int = 30,
    ):
        """两种鉴权方式，二选一：
        - 服务 API KEY（sk- 开头，元宝搜索控制台创建）：env TENCENTCLOUD_WSA_APIKEY
        - 腾讯云账号密钥（AKID 开头 + SecretKey，TC3 签名）：env TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY
        """
        self.api_key = api_key or os.getenv("TENCENTCLOUD_WSA_APIKEY", "")
        self.secret_id = secret_id or os.getenv("TENCENTCLOUD_SECRET_ID", "")
        self.secret_key = secret_key or os.getenv("TENCENTCLOUD_SECRET_KEY", "")
        if self.api_key.startswith("AKID") and not self.secret_id:
            raise SearchError(
                "TENCENTCLOUD_WSA_APIKEY 填的是腾讯云 SecretId（AKID 开头），不是元宝搜索的服务 API KEY（sk- 开头）。"
                "请到元宝搜索控制台创建服务 API KEY，或改填 TENCENTCLOUD_SECRET_ID + TENCENTCLOUD_SECRET_KEY。"
            )
        if not self.api_key and not (self.secret_id and self.secret_key):
            raise SearchError("缺少鉴权信息：请在 .env 配置 TENCENTCLOUD_WSA_APIKEY，或 TENCENTCLOUD_SECRET_ID + TENCENTCLOUD_SECRET_KEY")
        self.auth_mode = "apikey" if self.api_key else "tc3"
        self.use_cache = use_cache
        self.timeout = timeout
        self.calls = 0  # 本次进程真实发出的请求数（不含缓存命中）
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 公开方法 -------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        mode: int | None = None,
        site: str | None = None,
        cnt: int | None = None,
        industry: str | None = None,
        freshness: str | None = None,
        deeplinks: bool | None = None,
        channel: str = "",
    ) -> SearchResult:
        payload: dict[str, Any] = {"Query": query}
        if mode is not None:
            payload["Mode"] = mode
        if site:
            payload["Site"] = site
        if cnt:
            payload["Cnt"] = cnt
        if industry:
            payload["Industry"] = industry
        if freshness:
            payload["Freshness"] = freshness
        if deeplinks is not None:
            payload["Deeplinks"] = deeplinks

        key = self._cache_key(payload)
        cache_file = CACHE_DIR / f"{key}.json"
        if self.use_cache and cache_file.exists():
            data = json.loads(cache_file.read_text("utf-8"))
            return self._build(query, payload, data, channel, cached=True, elapsed=0.0)

        t0 = time.time()
        data = self._request(payload)
        elapsed = time.time() - t0
        self.calls += 1
        if self.use_cache:
            cache_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        return self._build(query, payload, data, channel, cached=False, elapsed=elapsed)

    # ---- 内部 -------------------------------------------------------------
    def _request(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(3):
            if self.auth_mode == "apikey":
                url = ENDPOINT
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                }
            else:
                url = f"https://{TC3_HOST}/"
                headers = self._tc3_headers(body)
            try:
                r = requests.post(url, data=body, headers=headers, timeout=self.timeout)
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            resp = data.get("Response", {})
            if "Error" in resp:
                code = resp["Error"].get("Code", "")
                if code == "RequestLimitExceeded" and attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise SearchError(f"{code}: {resp['Error'].get('Message')} (RequestId={resp.get('RequestId')})")
            return data
        raise SearchError(f"请求失败: {last_err}")

    def _tc3_headers(self, body: bytes) -> dict:
        """腾讯云 API 3.0 TC3-HMAC-SHA256 签名（官方文档的标准算法）。"""
        ts = int(time.time())
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{TC3_HOST}\nx-tc-action:{TC3_ACTION.lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(body).hexdigest()
        canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        scope = f"{date}/{TC3_SERVICE}/tc3_request"
        string_to_sign = f"TC3-HMAC-SHA256\n{ts}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = _hmac(("TC3" + self.secret_key).encode("utf-8"), date)
        k_service = _hmac(k_date, TC3_SERVICE)
        k_signing = _hmac(k_service, "tc3_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"TC3-HMAC-SHA256 Credential={self.secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": ct,
            "Host": TC3_HOST,
            "X-TC-Action": TC3_ACTION,
            "X-TC-Timestamp": str(ts),
            "X-TC-Version": TC3_VERSION,
        }

    @staticmethod
    def _cache_key(payload: dict) -> str:
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(s.encode("utf-8")).hexdigest()

    @staticmethod
    def _build(query, payload, data, channel, cached, elapsed) -> SearchResult:
        resp = data.get("Response", {})
        pages = [Page.from_raw(p, query=query, channel=channel) for p in resp.get("Pages", []) or []]
        return SearchResult(
            query=query,
            params=payload,
            pages=pages,
            version=resp.get("Version", ""),
            msg=resp.get("Msg", ""),
            request_id=resp.get("RequestId", ""),
            cached=cached,
            elapsed=elapsed,
        )


if __name__ == "__main__":  # 最简调用：python -m suyuan.search "查询词"
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    q = sys.argv[1] if len(sys.argv) > 1 else "三星堆的由来"
    res = YuanbaoSearch(use_cache=False).search(q, cnt=10)
    print(f"version={res.version} msg={res.msg!r} request_id={res.request_id} elapsed={res.elapsed:.2f}s")
    for i, p in enumerate(res.pages, 1):
        print(f"{i:2d}. [{p.score:.2f}] {p.date} {p.site} | {p.title}\n    {p.url}\n    {p.snippet[:120]}")
