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
from . import ingest, suggestions


def _frame(event: str, data: dict[str, Any]) -> str:
    """拼装一条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_events(user_id: int, req: ChatRequest, provider: LlmProvider) -> AsyncIterator[str]:
    """产出 chat/stream 的完整事件序列，检索范围限定在请求者自己的切片内。"""
    started = time.perf_counter()
    is_direct = req.mode == "direct"
    # direct 模式不检索，就不该报「切分问题 / 检索 / 重排」三个状态帧。
    # 之前无条件发这三帧，前端会把「检索中」显示给一个根本没查库的请求 —— 用户
    # 看着「正在检索知识库」等了 1 秒，最后拿到一段与资料无关的自由回答（F06 明确
    # 要求 direct 侧显示「未引用知识库资料」）。只保留 generating 这一帧，
    # 与 `retrieval` 帧「direct 时省略」的既有契约保持一致。
    if not is_direct:
        for stage in ("rewriting", "retrieving", "reranking"):
            yield _frame("status", {"stage": stage})

    # direct 模式不检索：A2 的提示词明确要求 direct 走空引用，避免把 RAG 的答案
    # 伪装成「没检索也能答对」。
    # options.rerank 是参数实验的重排轴覆盖项：None 表示沿用全局配置。
    rerank_option = req.options.get("rerank") if isinstance(req.options, dict) else None
    rerank = rerank_option if isinstance(rerank_option, bool) else None
    citations = (
        [] if is_direct else ingest.context_citations(
            user_id, req.question, req.k,
            [turn.model_dump() for turn in req.history],
            rerank=rerank,
        )
    )
    if not is_direct:
        yield _frame("retrieval", {"citations": citations})

    yield _frame("status", {"stage": "generating"})
    collected: list[str] = []
    async for token in provider.answer(req.question, citations, direct=is_direct):
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
        # N2：追问推荐真生成。必须在 token 全部推完之后才问 —— 不知道答了什么，
        # 就不知道用户接下来会问什么。失败一律空数组，不影响本帧其它字段。
        #
        # direct 模式不给推荐：没有检索资料，就没有「资料里有据可答」的追问可推，
        # 编几条等于让用户点进去问一个资料答不了的问题。Java 侧 MockAiClient 同一规则。
        "suggestions": (
            [] if req.mode == "direct"
            else await suggestions.generate(provider, req.question, answer, citations)
        ),
    }
    if req.mode == "both":
        # 对照模式的「直接答」侧必须**真正独立生成**。
        #
        # 之前这里写的是 done["direct_content"] = answer —— 直接把 rag 侧的答案
        # 复制一份。后果是两栏内容完全相同，而且 direct 侧还带着 rag 的 [1] 引用标记，
        # 一个根本没检索的模式却挂着来源编号。F06「对照」的全部意义（比较有资料
        # 与无资料的差别）被这一行抹掉了，用户看到的其实是同一份答案。
        #
        # 串行生成：复用同一 provider、citations 置空、direct=True。选串行而不是
        # 并行是有意的 —— 并行要交错复用同一条 SSE 流，前端得按 side 字段分流，
        # 复杂度翻倍；而对照本来就是「多花一点时间看清差别」的模式，耗时翻倍可接受。
        direct_collected: list[str] = []
        async for token in provider.answer(req.question, [], direct=True):
            direct_collected.append(token)
        done["direct_message_id"] = "py-direct-" + uuid.uuid4().hex[:8]
        done["direct_content"] = "".join(direct_collected)
    yield _frame("done", done)
