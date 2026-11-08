"""内部接口路由：所有用户态端点都要求 X-User-Id，并按用户隔离数据。"""

from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..core.llm.provider import provider_from_settings
from ..schemas.models import ChatRequest, EvalRequest, ParseRequest, RetrieveRequest
from ..services import chat, ingest, state
from .deps import STARTED_AT, envelope, require_token, require_user_id

router = APIRouter(prefix="/internal/v1")


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """对话流式回答，检索只取请求者自己最近一次成功任务的切片。"""
    settings = get_settings()
    provider = provider_from_settings(settings)
    return StreamingResponse(
        chat.sse_events(user_id, req, provider),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/documents/parse")
async def parse_documents(
    req: ParseRequest,
    bg: BackgroundTasks,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """提交解析任务；(user_id, submission_key) 相同则复用已有任务。"""
    task_id, created = state.create_task(
        user_id,
        req.submission_key,
        req.generation,
        len(req.documents),
        req.chunk_size,
        req.overlap,
    )
    if created:
        bg.add_task(ingest.run_ingest, user_id, task_id, req)
        doc_count = len(req.documents)
    else:
        existing = state.get_task(user_id, task_id)
        doc_count = int(existing["doc_count"]) if existing else len(req.documents)
    return envelope({"task_id": task_id, "doc_count": doc_count})


@router.get("/ingest/{task_id}")
async def ingest_status(
    task_id: str,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """查询解析任务；跨用户一律按不存在处理。

    终态时一并回传本次任务的切片清单：Java 靠它把片段落进自己的 chunk 表，
    {@code GET /api/v1/chunks} 与引用高亮才有数据。未完成时给空数组，不提前泄露半成品。
    """
    task = state.get_task(user_id, task_id)
    if task is None:
        raise HTTPException(404, detail=envelope(None, 40402, "任务不存在"))
    payload = dict(task)
    payload["chunks"] = ingest.task_chunks(user_id, task_id) if task["status"] == "SUCCEEDED" else []
    return envelope(payload)


@router.get("/documents/{doc_id}/status")
async def document_status(
    doc_id: str,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """查询文档状态；跨用户一律按不存在处理。"""
    document = state.get_document(user_id, doc_id)
    if document is None:
        raise HTTPException(404, detail=envelope(None, 40401, "资料不存在"))
    return envelope(document)


@router.get("/index/status")
async def index_status(
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """索引清单取该用户最近一次成功任务，无任务时回退默认切片参数。"""
    settings = get_settings()
    return envelope(
        ingest.index_manifest(
            user_id,
            settings.embedding_model,
            ingest.DEFAULT_CHUNK_SIZE,
            ingest.DEFAULT_OVERLAP,
        )
    )


@router.post("/retrieve")
async def retrieve(
    req: RetrieveRequest,
    retrieval_mode: str | None = None,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """检索接口；无命中返回空引用列表。retrieval_mode 覆盖默认档位。"""
    return envelope(ingest.retrieve_data(user_id, req, mode=retrieval_mode))


@router.post("/eval/batch")
async def eval_batch(
    req: EvalRequest,
    _token: str = Depends(require_token),
    user_id: int = Depends(require_user_id),
):
    """批量评测：direct 与 rag 各答一次，按关键词分组判定是否命中。

    与对话链路共用同一套检索与生成，`rag_sources` 是本次 RAG 答案实际用到的
    chunk_id 列表，长度受 `k` 约束。评测只读，不写对话、不写反馈。
    """
    provider = provider_from_settings(get_settings())
    results = []
    for case in req.cases:
        started = time.perf_counter()
        direct_answer = await _collect(provider, case.question, [])
        citations = ingest.context_citations(user_id, case.question, req.k)
        rag_answer = await _collect(provider, case.question, citations)
        results.append(
            {
                "question_id": case.id,
                "direct_answer": direct_answer,
                "direct_passed": _judge(direct_answer, case.keywords),
                "rag_answer": rag_answer,
                "rag_passed": _judge(rag_answer, case.keywords),
                "rag_sources": [item["chunk_id"] for item in citations],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
    return envelope(
        {
            "cases": results,
            "total": len(results),
            "passed_direct": sum(1 for row in results if row["direct_passed"]),
            "passed_rag": sum(1 for row in results if row["rag_passed"]),
        }
    )


async def _collect(provider, question: str, citations: list[dict]) -> str:
    """把流式增量拼成整段回答，评测需要完整文本才能判分。"""
    chunks: list[str] = []
    async for token in provider.answer(question, citations):
        chunks.append(token)
    return "".join(chunks)


def _judge(answer: str, keywords: str) -> bool:
    """关键词分组判分：组内 `/` 表示同义，组间 `|` 表示必须全部命中。

    与 Java 侧 `EvalServiceImpl.judge` 的分组语义保持一致，避免两侧对同一答案
    给出不同结论。
    """
    if not keywords:
        return False
    for group in keywords.split("|"):
        alternatives = [word.strip() for word in group.split("/") if word.strip()]
        if not alternatives:
            continue
        if not any(word in answer for word in alternatives):
            return False
    return True



@router.get("/health")
async def health(_token: str = Depends(require_token)):
    """健康检查；非用户态端点，不需要 X-User-Id。"""
    settings = get_settings()
    return envelope(
        {
            "status": "UP",
            "version": "0.1.0",
            "embedding_model": settings.embedding_model,
            "llm_model": settings.llm_model,
            "uptime_seconds": int(time.time() - STARTED_AT),
        }
    )
