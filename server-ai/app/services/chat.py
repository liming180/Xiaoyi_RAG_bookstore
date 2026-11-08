"""对话 SSE 流：状态事件、检索事件、增量 token、结束事件。

与 A1 的差别只有一处：`retrieval` 帧现在来自真实检索（`ingest.context_citations`），
生成阶段把引用作为上下文交给 provider，并在结束后保证回答里带合法来源编号。
事件顺序与字段名不变，J3 的既有断言继续成立。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

from ..core.llm.provider import LlmProvider
from ..core.rag.prompt import enforce_citations
from ..schemas.models import ChatRequest
from . import ingest


def _frame(event: str, data: dict[str, Any]) -> str:
    """拼装一条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_events(user_id: int, req: ChatRequest, provider: LlmProvider) -> AsyncIterator[str]:
    """产出 chat/stream 的完整事件序列，检索范围限定在请求者自己的切片内。"""
    started = time.perf_counter()
    for stage in ("rewriting", "retrieving", "reranking"):
        yield _frame("status", {"stage": stage})

    # direct 模式不检索：A2 的提示词明确要求 direct 走空引用，避免把 RAG 的答案
    # 伪装成「没检索也能答对」。
    citations = (
        [] if req.mode == "direct" else ingest.context_citations(user_id, req.question, req.k)
    )
    if req.mode != "direct":
        yield _frame("retrieval", {"citations": citations})

    yield _frame("status", {"stage": "generating"})
    collected: list[str] = []
    async for token in provider.answer(req.question, citations):
        collected.append(token)
        yield _frame("token", {"content": token})

    answer = "".join(collected)
    if req.mode != "direct" and citations:
        suffix = enforce_citations(answer, citations)
        if suffix != answer:
            # 模型没按格式标注来源时补一行，保证前端能渲染可点引用。
            extra = suffix[len(answer) :]
            answer = suffix
            yield _frame("token", {"content": extra})

    done: dict[str, Any] = {
        "message_id": "py-m-" + uuid.uuid4().hex[:8],
        "usage": provider.usage(req.question, answer),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "degraded": False,
        "suggestions": ["可以继续了解吗？"],
    }
    if req.mode == "both":
        done["direct_message_id"] = "py-direct-" + uuid.uuid4().hex[:8]
        done["direct_content"] = answer
    yield _frame("done", done)
