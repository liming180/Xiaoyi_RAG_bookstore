"""模型调用：真实接口通道（urllib + 禁重定向）+ 离线模拟通道。

离线模拟档（provider=mock）不是“假数据”，而是可复现的规则式回答器：
它在被取回的片段里按“问题要点 → 证据句”匹配，命中才引用、未命中就说未提供，
并对未核实片段与夹带指令一律不采纳 —— 与真实模型遵守同一套提示词约束。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .mockdata import DIRECT_FALLBACK, DIRECT_PRESETS, INJECTION_MARKERS
from .settings import AppError, is_mock

_SENTENCE_RE = re.compile(r"[^。！？；\n]+[。！？；]?")

# 问题要点 → 证据要求。triggers 命中问题即认为该要点被问到；
# must 为证据句必须包含的原文片段；miss 为未命中时的说法（须含“没有提供”类表述）。
ASPECTS: list[dict[str, Any]] = [
    {
        "name": "活动时间",
        "triggers": ["每周几", "几点举行", "什么时候举行", "活动时间", "读书会通常"],
        "must": ["14:00至16:00"],
        "miss": "资料中没有提供常规活动的举办时间。",
    },
    {
        "name": "结束时间",
        "triggers": ["几点结束", "什么时候结束", "结束时间"],
        "must": ["16:00"],
        "miss": "资料中没有提供活动结束时间。",
    },
    {
        "name": "报名截止",
        "triggers": ["报名", "截止"],
        "must": ["18:00"],
        "miss": "资料中没有提供报名截止时间。",
    },
    {
        "name": "借阅数量",
        "triggers": ["借阅几本", "能借几本", "最多能借", "借几本", "借阅数量", "几本普通图书"],
        "must": ["4本普通图书"],
        "miss": "资料中没有提供普通图书的借阅数量。",
    },
    {
        "name": "借期",
        "triggers": ["借多久", "借期", "多长时间"],
        "must": ["21天"],
        "miss": "资料中没有提供普通图书的借期。",
    },
    {
        "name": "续借规则",
        "triggers": ["续借"],
        "must": ["续借1次"],
        "miss": "资料中没有提供续借次数与续借天数。",
    },
    {
        "name": "续借限制",
        "triggers": ["续借"],
        "must": ["不能续借"],
        "miss": "资料中没有说明哪些图书不能续借。",
    },
    {
        "name": "空间人数",
        "triggers": ["几人", "多少人", "人数"],
        "must": ["3至6人"],
        "miss": "资料中没有提供讨论空间的人数要求。",
    },
    {
        "name": "空间时长",
        "triggers": ["每次最长", "最长多久", "使用时长"],
        "must": ["2小时"],
        "miss": "资料中没有提供讨论空间每次的使用时长。",
    },
    {
        "name": "取消规则",
        "triggers": ["取消", "提前多久"],
        "must": ["30分钟"],
        "miss": "资料中没有提供取消预约的时间要求。",
    },
    {
        "name": "预约天数",
        "triggers": ["可提前的天数", "提前几天", "提前多少天", "提前预约"],
        "must": ["提前2天"],
        "miss": "资料中没有提供讨论空间可提前预约的天数。",
    },
    {
        "name": "费用",
        "triggers": ["费用", "收费", "多少钱", "交多少"],
        "must": ["收费标准", "收费事项", "免费"],
        "miss": "资料中没有提供参加读书会的收费标准，无法确定具体费用。",
    },
    {
        "name": "联系电话",
        "triggers": ["联系电话", "电话", "联系方式"],
        "must": ["联系电话", "工作人员电话"],
        "miss": "资料中没有提供管理员或工作人员的联系电话。",
    },
]

# 这些说法表示“资料本身声明不含该信息”，属于否定式证据：
# 命中时只能用来支持“没有提供”，不能当成规则答案。
_ABSENCE_MARKERS = ("不包含", "没有提供", "未提供", "不涉及", "没有涉及", "没有相关", "未说明", "没有说明")


# ---------------------------------------------------------------- 真实通道
def _no_redirect() -> urllib.request.OpenerDirector:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):   # noqa: D401
            return None

    return urllib.request.build_opener(NoRedirect())


def _validate_endpoint(endpoint: str, label: str) -> None:
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise AppError(f"{label} 须填写完整的 HTTPS 接口地址。")
    if any(ch.isspace() or ord(ch) < 32 for ch in endpoint):
        raise AppError(f"{label} 不能包含空白或控制字符。")


def _make_payload(cfg: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": cfg.get("model", ""), "messages": messages, "stream": False}
    for key in ("temperature", "max_tokens"):
        if cfg.get(key) is not None:
            payload[key] = cfg[key]
    return payload


def call_model(cfg: dict[str, Any], api_key: str, messages: list[dict[str, str]]) -> tuple[str, Any]:
    """Chat Completions，失败时抛中文错误且不进入会话历史。"""
    _validate_endpoint(cfg.get("endpoint", ""), "endpoint")
    if not isinstance(cfg.get("model"), str) or not cfg["model"].strip():
        raise AppError("model 须填写非空的模型名称。")
    if not api_key:
        raise AppError("缺少对话接口密钥，请先填写密钥。")
    try:
        body = json.dumps(_make_payload(cfg, messages), ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            cfg["endpoint"], data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        )
    except (TypeError, ValueError, UnicodeError):
        raise AppError("请求配置、消息或密钥格式不正确，请核对后重试。") from None
    try:
        with _no_redirect().open(request, timeout=cfg.get("timeout_seconds", 45)) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise AppError(f"HTTP {exc.code}，请按手册排查；本次未加入会话历史。") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AppError(f"连接失败或超时：{exc}；本次未加入会话历史。") from None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        text = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
        raise AppError("接口响应结构不符，请教师核对接入层。") from None
    if not isinstance(text, str) or not text.strip():
        raise AppError("未收到非空文本回答，请教师核对模型及响应格式。")
    return text, data.get("usage")


# ---------------------------------------------------------------- 离线模拟通道
def _sentences(text: str) -> list[str]:
    return [piece.strip() for piece in _SENTENCE_RE.findall(text) if piece.strip()]


def _has_injection(text: str) -> bool:
    return any(marker in text for marker in INJECTION_MARKERS)


def _aspects_for(question: str) -> list[dict[str, Any]]:
    return [aspect for aspect in ASPECTS if any(t in question for t in aspect["triggers"])]


def _bigrams(text: str) -> set[str]:
    clean = "".join(ch for ch in text if not ch.isspace())
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def _is_absence(sentence: str) -> bool:
    """该句是否只是“资料里没有这项信息”的声明，而不是规则本身。"""
    return any(marker in sentence for marker in _ABSENCE_MARKERS)


def mock_answer(question: str, hits: list[dict[str, Any]]) -> str:
    """在取回的片段里找证据句；未命中即明确说未提供，绝不编造。"""
    if not hits:
        return DIRECT_PRESETS.get(question, DIRECT_FALLBACK)

    evidence: dict[str, str] = {}          # 证据句 -> chunk_id（保持出现顺序）
    misses: list[str] = []
    ignored: list[str] = []

    aspects = _aspects_for(question)
    for aspect in aspects:
        found = False
        for hit in hits:
            if not hit.get("verified", True):
                continue
            for sentence in _sentences(hit["text"]):
                if _has_injection(sentence):
                    continue
                if not all(m in sentence for m in aspect["must"]):
                    continue
                # 命中“本文不包含……”这类否定式声明时，只证明资料没写，不能当答案引用
                if _is_absence(sentence):
                    continue
                evidence.setdefault(sentence, hit["chunk_id"])
                found = True
                break
            if found:
                break
        if not found:
            misses.append(aspect["miss"])

    # 未触发任何要点时，退化为“按问题相关度取最相关的两句话”
    if not aspects:
        query_grams = _bigrams(question)
        ranked: list[tuple[float, str, str]] = []
        for hit in hits:
            if not hit.get("verified", True):
                continue
            for sentence in _sentences(hit["text"]):
                if _has_injection(sentence):
                    continue
                overlap = len(query_grams & _bigrams(sentence))
                if overlap:
                    ranked.append((overlap, sentence, hit["chunk_id"]))
        ranked.sort(key=lambda item: -item[0])
        for _, sentence, chunk_id in ranked[:2]:
            evidence.setdefault(sentence, chunk_id)
        if not evidence:
            misses.append("资料中没有提供与这个问题相关的信息。")

    # 未核实片段里的相关说法：明确记录为“不采用”，但不引用其原文。
    # 只有确实问到某个要点时才追加这段提醒，避免无关问题也带上这句噪音。
    if aspects:
        for hit in hits:
            if hit.get("verified", True):
                continue
            for sentence in _sentences(hit["text"]):
                if _has_injection(sentence):
                    ignored.append(f"留言 {hit['chunk_id']} 中夹带了要求助手改变回答规则的指令，已按资料对待、不予执行。")
                    break
                if any(all(m in sentence for m in aspect["must"]) for aspect in aspects):
                    ignored.append(f"留言 {hit['chunk_id']} 中的相关说法未经核实，不采用。")
                    break

    lines: list[str] = []
    for sentence, chunk_id in evidence.items():
        lines.append(f"{sentence}[{chunk_id}]")
    if misses:
        # 去掉每条 miss 末尾的句号再拼接，避免出现「要求。；资料中没有……」这种双标点
        lines.append("；".join(m.rstrip("。；") + "。" for m in misses))
    lines.extend(dict.fromkeys(ignored))
    if not lines:
        return "资料中没有提供相关信息，建议咨询管理员。"
    return "\n".join(lines)


def mock_usage(prompt_chars: int, answer: str) -> dict[str, int]:
    return {
        "prompt_tokens": max(1, prompt_chars // 2),
        "completion_tokens": max(1, len(answer) // 2),
        "total_tokens": max(2, (prompt_chars + len(answer)) // 2),
    }


def answer(cfg: dict[str, Any], api_key: str, messages: list[dict[str, str]],
           question: str, hits: list[dict[str, Any]]) -> tuple[str, Any]:
    """统一出口：mock 走本地规则，real 走教师接口。"""
    if is_mock(cfg):
        text = mock_answer(question, hits)
        prompt_chars = sum(len(item.get("content", "")) for item in messages)
        return text, mock_usage(prompt_chars, text)
    return call_model(cfg, api_key, messages)
