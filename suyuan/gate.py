"""安全闸：在检索之前拦下两类输入，不消耗搜索额度。

1. 个人信息 / 针对具体个人的隐私与指控（手机号、证件号、住址、行踪、私生活、人肉搜索等）
2. 敏感时政（国家领导人个人、政治体制与意识形态争议、民族宗教、港澳台与外交敏感事件、军事机密等）

普通的民生政策、部门通知、社会新闻、企业与产品信息照常放行。
先用正则抓明显的个人信息，再用大模型做一次分类；没有大模型时只靠正则。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLM

# ---- 正则层：明显的个人信息 -------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号码"),
    (re.compile(r"(?<![0-9Xx])\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])"), "身份证号码"),
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "银行卡号"),
    (re.compile(r"(家庭住址|住址是|住在|家住)[^，。；\n]{0,6}(省|市|区|县|路|街|小区|栋|单元|号楼|室)"), "具体住址"),
    (re.compile(r"人肉|开盒|扒皮|查他(的)?(住址|电话|信息)|曝光(他|她|其)(的)?(住址|电话|身份证|家人)"), "人肉搜索"),
    (re.compile(r"(车牌|车牌号)[：:是为]?\s*[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6}"), "车牌号"),
]

_PII_WHITELIST_CONTEXT = re.compile(r"热线|客服|举报电话|官方电话|咨询电话|服务热线|电话号码为公开")

GATE_SYSTEM = """你是内容审核员，判断一条待核查的网络传闻是否允许进入「公开信息核查」流程。只输出 JSON。

拒绝（allowed=false）的两类：
A. 个人隐私类：针对具体自然人（包括公众人物）的私生活、健康、感情、家庭、行踪、财产、联系方式、证件信息，或对具体个人的道德指控、人肉搜索。例：某人出轨、某人患病、某人住哪、某人是骗子。
B. 敏感时政类：涉及国家领导人个人及其家属、政治体制与意识形态争议、民族宗教敏感议题、港澳台与外交敏感事件、军事部署与机密、重大政治事件的传闻或评价。

放行（allowed=true）的：民生政策（医保、社保、教育、交通、税费等）、政府部门与企业的公开通知、社会新闻与公共安全事件、科普与健康常识、商业与产品信息、公众人物的公开职务行为与公开作品。

注意：提到政府部门名称或政策本身不等于敏感时政；只有涉及上面 B 类列出的具体范围才拒绝。拿不准时放行。

输出：{"allowed": true/false, "category": "ok" | "privacy" | "politics", "reason": "一句话中文说明"}"""


@dataclass
class GateResult:
    allowed: bool
    category: str = "ok"  # ok / privacy / politics
    reason: str = ""
    by: str = "none"  # regex / llm / none


def regex_check(text: str) -> GateResult | None:
    if _PII_WHITELIST_CONTEXT.search(text):
        return None
    for pat, name in _PII_PATTERNS:
        if pat.search(text):
            return GateResult(False, "privacy", f"内容包含{name}等个人信息，本工具不核查涉及具体个人隐私的内容。", by="regex")
    return None


def check(text: str, llm: LLM | None) -> GateResult:
    r = regex_check(text)
    if r is not None:
        return r
    if llm is None:
        return GateResult(True, "ok", "", by="regex")
    try:
        data = llm.chat_json(GATE_SYSTEM, f"待核查内容：\n{text[:1200]}", max_tokens=200)
    except Exception:  # noqa: BLE001  审核模型失败时不拦截，交给后续流程
        return GateResult(True, "ok", "", by="llm-failed")
    allowed = bool(data.get("allowed", True))
    cat = str(data.get("category") or ("ok" if allowed else "politics"))
    if cat not in ("ok", "privacy", "politics"):
        cat = "ok" if allowed else "politics"
    reason = str(data.get("reason") or "")
    if not allowed and not reason:
        reason = "涉及个人隐私" if cat == "privacy" else "涉及敏感时政"
    return GateResult(allowed, cat if not allowed else "ok", reason, by="llm")


REFUSAL_TEXT = {
    "privacy": "这条内容涉及具体个人的隐私或指控。溯源只核查公开的公共信息，不对个人做调查，也不会去搜索任何人的个人信息。",
    "politics": "这条内容涉及敏感时政议题，不在本工具的核查范围内。溯源只处理民生政策、公共事件和社会传闻这类可以用公开权威信息核实的内容。",
}
