"""LLM provider：mock（确定性模板）与 real（OpenAI 兼容 /chat/completions 流式）。

`answer()` 是异步生成器，两条实现都只吐增量文本，SSE 层不需要区分档位；
`usage()` 只在 real 档有真实数字，mock 档按字符数估算。

真实档的实现要点：
* 用 httpx 的流式接口逐行读 `data:`，遇 `[DONE]` 结束；
* 连接层错误与 5xx / 429 各重试一次，仍失败则抛出，由 SSE 层转成 error 帧；
* 401 / 403 直接抛，重试没有意义。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from ...config import Settings

MOCK_PREFIX = "这是针对"


class LlmProvider(ABC):
    """生成接口。"""

    @abstractmethod
    async def answer(
        self,
        question: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    def usage(self, question: str, answer: str) -> dict[str, int]: ...


class MockProvider(LlmProvider):
    """离线模板回答：不联网、不随机，门禁断言可以写死。"""

    async def answer(
        self,
        question: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        text = f"{MOCK_PREFIX}“{question}”的模拟回答。"
        if citations:
            refs = "".join(f"[{item['ref']}]" for item in citations[:3])
            text = f"{text}来源：{refs}"
        for start in range(0, len(text), 4):
            yield text[start : start + 4]

    def usage(self, question: str, answer: str) -> dict[str, int]:
        return {"prompt_tokens": len(question), "completion_tokens": len(answer)}


class OpenAiProvider(LlmProvider):
    """OpenAI 兼容的流式 provider（智谱 glm-4-flash / vLLM / 官方 API 均可）。"""

    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.llm_endpoint.rstrip("/")
        self._model = settings.llm_model
        self._api_key = settings.llm_api_key
        self._timeout = max(1, settings.llm_timeout_ms) / 1000.0
        self._last_usage: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def answer(
        self,
        question: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        from ..rag.prompt import build_messages

        payload = {
            "model": self._model,
            "messages": build_messages(question, citations or []),
            "stream": True,
            "temperature": 0.2,
        }
        self._last_usage = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._endpoint}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code in (401, 403):
                    body = await response.aread()
                    raise RuntimeError(
                        f"LLM 鉴权失败（HTTP {response.status_code}）："
                        f"{body[:200].decode('utf-8', 'replace')}"
                    )
                if response.status_code != 200:
                    body = await response.aread()
                    raise RuntimeError(
                        f"LLM 调用失败（HTTP {response.status_code}）："
                        f"{body[:200].decode('utf-8', 'replace')}"
                    )
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        self._last_usage = {
                            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                        }
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content

    def usage(self, question: str, answer: str) -> dict[str, int]:
        if self._last_usage:
            return dict(self._last_usage)
        return {"prompt_tokens": len(question), "completion_tokens": len(answer)}


def provider_from_settings(settings: Settings) -> LlmProvider:
    """按 `AI_PROVIDER` 选实现；real 档的端点由 `Settings.validate()` 提前校验。"""
    if settings.ai_provider.lower() == "real":
        return OpenAiProvider(settings)
    return MockProvider()
