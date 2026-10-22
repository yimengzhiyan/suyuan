"""信源分级。

个人版元宝搜索不返回 authority_level，这里用域名白名单自建五档权威度：
  1 政府/官方  2 中央媒体  3 主流媒体  4 门户/垂直  5 自媒体/未知
匹配规则：域名等于或以 ".后缀" 结尾即命中；多档命中取最小（最权威）。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

TIER_NAMES: dict[int, str] = {
    1: "政府/官方",
    2: "中央媒体",
    3: "主流媒体",
    4: "门户/垂直",
    5: "自媒体/未知",
}

# 专门的辟谣平台：中国互联网联合辟谣平台、腾讯较真
DEBUNK_SITES = ("piyao.org.cn", "vp.fact.qq.com")

TIER_DOMAINS: dict[int, tuple[str, ...]] = {
    1: ("gov.cn", "edu.cn", "piyao.org.cn", "12377.cn"),
    2: (
        "xinhuanet.com", "news.cn", "people.com.cn", "cctv.com", "cctv.cn", "huanqiu.com", "peopleapp.com", "jingjiribao.cn", "cyol.com", "china.com.cn", "chinanews.com.cn", "cnr.cn",
        "chinanews.com", "chinadaily.com.cn", "gmw.cn", "youth.cn",
        "qstheory.cn", "ce.cn", "cgtn.com", "81.cn", "legaldaily.com.cn",
    ),
    3: (
        "thepaper.cn", "bjnews.com.cn", "caixin.com", "yicai.com", "jiemian.com",
        "cls.cn", "stcn.com", "cs.com.cn", "nfnews.com", "southcn.com",
        "jfdaily.com", "shobserver.com", "bjd.com.cn", "news.sina.com.cn",
        "news.qq.com", "news.163.com", "ifeng.com", "vp.fact.qq.com",
    ),
    4: (
        "sina.com.cn", "qq.com", "163.com", "sohu.com", "36kr.com", "zhihu.com",
        "bilibili.com", "ithome.com", "mp.weixin.qq.com", "baike.baidu.com",
        "wikipedia.org",
    ),
}


_BIG5_RE = re.compile(r"^https?://[^/]+/gate/big5/([^/]+)(/.*)?$", re.I)


def canonical_url(url: str) -> str:
    """规范化 URL 用于去重：繁体镜像（big5.xxx/gate/big5/原站）还原为原站地址，去掉末尾斜杠。"""
    u = (url or "").strip()
    m = _BIG5_RE.match(u)
    if m:
        u = "https://" + m.group(1) + (m.group(2) or "/")
    return u.rstrip("/")


def domain_of(url: str) -> str:
    """取 URL 的主机名（小写、去掉 www. 与端口）。传入裸域名也可。"""
    if not url:
        return ""
    s = url.strip()
    if "://" not in s:
        s = "http://" + s
    host = (urlparse(s).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _match(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def tier_of(url: str) -> int:
    """返回信源等级 1~5，未知域名为 5。"""
    host = domain_of(url)
    if not host:
        return 5
    for tier in sorted(TIER_DOMAINS):
        if any(_match(host, d) for d in TIER_DOMAINS[tier]):
            return tier
    return 5


def tier_name(tier: int) -> str:
    return TIER_NAMES.get(tier, TIER_NAMES[5])


def is_debunk_site(url: str) -> bool:
    host = domain_of(url)
    return any(_match(host, d) for d in DEBUNK_SITES)
