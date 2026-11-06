"""对话 SSE 流：状态事件、检索事件、增量 token、结束事件。"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

from ..core.llm.provider import LlmProvider
from ..schemas.models import ChatRequest, RetrieveRequest
from . import ingest


def _frame(event: str, data: dict[str, Any]) -> str:
    """拼装一条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_events(user_id: int, req: ChatRequest, provider: LlmProvider) -> AsyncIterator[str]:
    """产出 chat/stream 的完整事件序列，检索范围限定在请求者自己的切片内。"""
    started = time.perf_counter()
    for stage in ("rewriting", "retrieving", "reranking"):
        yield _frame("status", {"stage": stage})
    result = ingest.retrieve_data(user_id, RetrieveRequest(question=req.question, k=req.k))
    yield _frame("retrieval", {"citations": result["citations"]})
    yield _frame("status", {"stage": "generating"})
    answer = ""
    async for token in provider.answer(req.question):
        answer += token
        yield _frame("token", {"content": token})
    done = {
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
