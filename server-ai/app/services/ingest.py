"""切片与任务推进：解析、切片、向量化、摘要四段进度，以及按用户范围检索。

A2 起，切分与检索不再用固定滑窗 + 关键词打分，而是：
1. `core.rag.splitter` 递归切分（Markdown 标题继承 + 段落/句子边界回退）；
2. `core.rag.embedder` 向量化（mock 档确定性哈希向量，real 档打 OpenAI 兼容服务）；
3. `core.vector_store.store` 落库并按 `user_id` / `task_id` 过滤检索。

SQLite（`state`）仍是切片元数据的权威来源：Java 建库轮询拿到 `data.chunks`
才会把片段缓存进 MySQL 的 chunk 表。向量只进向量库，不进 MySQL，也不进 SQLite。
"""

from __future__ import annotations

import time
from typing import Any

from ..config import get_settings
from ..core.rag import pipeline, prompt
from ..core.rag.embedder import Embedder, embedder_from_settings
from ..core.rag.splitter import MAX_CHUNKS_PER_DOC, MAX_DOCS_PER_USER, build_pieces
from ..core.vector_store.store import VectorStore, store_from_settings
from ..schemas.models import ParseDocument, ParseRequest, RetrieveRequest
from . import state

# 索引清单在无成功任务时回退到的默认切片参数。必须与 Java 侧
# `xiaoyi.index.default-chunk-size` / `default-overlap` 保持一致（180 / 30），
# 否则 `/index/status` 会因 manifest 与最近成功任务参数不符而恒为 needs_rebuild。
DEFAULT_CHUNK_SIZE = 180
DEFAULT_OVERLAP = 30

#: 引用里允许出现的 score_stage 取值（契约 enum）。
SCORE_STAGES = ("dense", "sparse", "rrf", "rerank")


class _Runtime:
    """进程内单例：向量库与 embedder 都要跨请求复用（建集合、缓存维度）。"""

    def __init__(self) -> None:
        self._store: VectorStore | None = None
        self._embedder: Embedder | None = None
        self._dim = 0

    def store(self) -> VectorStore:
        if self._store is None:
            self._store = store_from_settings(get_settings())
        return self._store

    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = embedder_from_settings(get_settings())
        return self._embedder

    def reset(self) -> None:
        """测试切换 settings 时清空缓存。"""
        self._store = None
        self._embedder = None
        self._dim = 0

    def ensure_dim(self, dim: int) -> int:
        """按需建集合；维度以 embedder 首次返回为准。"""
        if dim > 0 and dim != self._dim:
            self.store().ensure(dim)
            self._dim = dim
        return self._dim


runtime = _Runtime()


def _pause() -> None:
    """阶段间停顿：让 Java 的轮询看得见完整阶段序列。

    `ingest_stage_delay_ms` 默认 0（全速）；门禁环境把它调到大于 Java 轮询间隔，
    否则五个阶段会在毫秒内跑完，轮询只能抓到 parsing 与 done。只影响观测粒度，不改结果。
    """
    delay_ms = get_settings().ingest_stage_delay_ms
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def _document_no(user_id: int, doc_id: str) -> int:
    """取文档在该用户下的稳定编号，用于拼 D01-C001 这类 chunk_id。"""
    doc_no = state.document_number(user_id, doc_id)
    if doc_no <= 0 or doc_no > MAX_DOCS_PER_USER:
        return max(1, min(MAX_DOCS_PER_USER, doc_no or 1))
    return doc_no


def build_chunks(
    user_id: int,
    doc: ParseDocument,
    doc_no: int,
    req: ParseRequest,
) -> list[dict[str, Any]]:
    """把一份文档切成切片记录，字段与 Citation 契约一致。"""
    text = doc.text or doc.title or doc.name or ""
    title = doc.title or doc.name or doc.doc_id
    rows: list[dict[str, Any]] = []
    for piece in build_pieces(text, doc_no, req.chunk_size, req.overlap, title):
        rows.append(
            {
                "chunk_id": piece["chunk_id"],
                "doc_id": doc.doc_id,
                "doc_title": title,
                "heading_path": piece["heading_path"],
                "excerpt": piece["excerpt"],
                "start": piece["start"],
                "end": piece["end"],
                # 检索阶段会按向量相似度重算，这里只给一个占位值。
                "score": 0.0,
                "score_stage": "dense",
                "kind": piece["kind"],
                "verified": piece["verified"],
            }
        )
        if len(rows) >= MAX_CHUNKS_PER_DOC:
            break
    return rows


def _embed_and_store(
    user_id: int,
    task_id: str,
    rows: list[dict[str, Any]],
) -> int:
    """把切片向量化并写入向量库；返回写入条数。"""
    if not rows:
        return 0
    embedder = runtime.embedder()
    store = runtime.store()
    vectors = embedder.embed([row["excerpt"] for row in rows])
    if len(vectors) != len(rows):
        raise RuntimeError(f"向量条数与切片不符：切片 {len(rows)}，向量 {len(vectors)}")
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    if dim <= 0:
        raise RuntimeError("向量化返回空向量")
    runtime.ensure_dim(dim)
    payload = [{**row, "vector": vector} for row, vector in zip(rows, vectors)]
    # 先删同任务旧行，保证重放同一 submission_key 不会残留旧切片。
    store.delete_task(user_id, task_id)
    return store.upsert(user_id, task_id, payload)


def run_ingest(user_id: int, task_id: str, req: ParseRequest) -> None:
    """后台推进一次解析任务；任何异常都把任务置为 FAILED。"""
    try:
        state.update_task(user_id, task_id, status="RUNNING", stage="parsing", progress=20)
        for doc in req.documents:
            state.upsert_document(user_id, doc.doc_id, doc.title or doc.name or doc.doc_id, "PARSING", 0)
        _pause()

        state.update_task(user_id, task_id, stage="splitting", progress=45)
        planned: list[tuple[ParseDocument, list[dict[str, Any]]]] = []
        for doc in req.documents:
            parts = build_chunks(user_id, doc, _document_no(user_id, doc.doc_id), req)
            planned.append((doc, parts))
        _pause()

        state.update_task(user_id, task_id, stage="embedding", progress=70)
        # 同一任务的所有文档合成一批写入，保证一次任务只有一个 task_id 分区。
        flat = [row for _doc, parts in planned for row in parts]
        stored = _embed_and_store(user_id, task_id, flat)
        for doc, parts in planned:
            state.replace_chunks(user_id, task_id, doc.doc_id, parts)
            state.upsert_document(
                user_id,
                doc.doc_id,
                doc.title or doc.name or doc.doc_id,
                "INDEXED",
                len(parts),
            )
        _pause()

        state.update_task(user_id, task_id, stage="summarizing", progress=90, chunk_count=stored)
        _pause()
        state.update_task(
            user_id,
            task_id,
            status="SUCCEEDED",
            stage="done",
            progress=100,
            chunk_count=stored,
            finished_at=int(time.time()),
        )
    except Exception as exc:  # 解析失败必须落库，避免任务永远停在 RUNNING
        state.update_task(
            user_id,
            task_id,
            status="FAILED",
            stage="done",
            progress=100,
            error=f"解析任务失败：{exc}",
            finished_at=int(time.time()),
        )


def _latest_task(user_id: int) -> str | None:
    latest = state.latest_succeeded_task(user_id)
    return str(latest["task_id"]) if latest else None


def _fallback_rows(user_id: int, req: RetrieveRequest) -> list[dict[str, Any]]:
    """向量库没数据时退回 SQLite 的切片（重启后内存实现为空，靠这条兜底）。"""
    task_id = _latest_task(user_id)
    if task_id is None:
        return []
    rows = state.list_chunks(user_id, task_id)
    allowed = set(req.doc_ids) if req.doc_ids else None
    found = [
        row
        for row in rows
        if (allowed is None or row["doc_id"] in allowed) and (not req.kind or row["kind"] == req.kind)
    ]
    for row in found:
        row["score"] = 0.5
        row["score_stage"] = "dense"
    return found[: req.k]


def retrieve(user_id: int, req: RetrieveRequest) -> pipeline.RecallResult:
    """检索：问题向量化后在本人最近成功任务的切片里做纯向量 top-k。"""
    task_id = _latest_task(user_id)
    if task_id is None:
        return pipeline.RecallResult(citations=[], rows=[], elapsed_ms=0)

    question = (req.question or "").strip()
    if not question:
        # 无问题（如列举模式）按 chunk_id 顺序回传，分数置 0。
        rows = _fallback_rows(user_id, req)
        for row in rows:
            row["score"] = 0.0
        citations = [pipeline._as_citation(i + 1, row, "dense") for i, row in enumerate(rows)]
        traces = [pipeline._as_trace_row(i + 1, row, "dense") for i, row in enumerate(rows)]
        return pipeline.RecallResult(citations=citations, rows=traces, elapsed_ms=0)

    embedder = runtime.embedder()
    vector = embedder.embed([question])[0]
    runtime.ensure_dim(len(vector))
    result = pipeline.recall(
        runtime.store(),
        pipeline.RecallRequest(
            user_id=user_id,
            task_id=task_id,
            vector=vector,
            k=req.k,
            doc_ids=list(req.doc_ids),
            kind=req.kind,
        ),
        stage="dense",
    )
    if not result.citations:
        rows = _fallback_rows(user_id, req)
        citations = [pipeline._as_citation(i + 1, row, "dense") for i, row in enumerate(rows)]
        traces = [pipeline._as_trace_row(i + 1, row, "dense") for i, row in enumerate(rows)]
        return pipeline.RecallResult(citations=citations, rows=traces, elapsed_ms=result.elapsed_ms)
    return result


def retrieve_data(user_id: int, req: RetrieveRequest) -> dict[str, Any]:
    """检索结果；无命中时返回空引用列表，不伪造引用。"""
    result = retrieve(user_id, req)
    return {"citations": result.citations, "rows": result.rows}


def context_citations(user_id: int, question: str, k: int) -> list[dict[str, Any]]:
    """对话链路取上下文引用；供 `chat.sse_events` 复用同一套检索。"""
    result = retrieve(user_id, RetrieveRequest(question=question, k=k))
    return result.citations


def task_chunks(user_id: int, task_id: str) -> list[dict[str, Any]]:
    """把该任务的切片整理成 Java 侧 {@code AiChunk} 认得的字段名。

    Java 建库轮询拿到 {@code data.chunks} 才会把片段缓存进 MySQL 的 chunk 表并对外提供
    {@code GET /api/v1/chunks}；这里少给一层，前端知识库页就永远是空列表。

    只回传本人本次任务的切片：{@code state.list_chunks} 已按 {@code (user_id, task_id)} 限定范围。
    """
    return [
        {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "doc_title": row["doc_title"],
            "heading_path": row["heading_path"],
            "text": row["excerpt"],
            "start": row["start"],
            "end": row["end"],
            "kind": row["kind"],
            "verified": row["verified"],
        }
        for row in state.list_chunks(user_id, task_id)
    ]


def index_manifest(user_id: int, embedding_model: str, chunk_size: int, overlap: int) -> dict[str, Any]:
    """按该用户最近成功任务产出索引清单，无任务时回退请求默认值。"""
    latest = state.latest_succeeded_task(user_id)
    if latest is None:
        return {
            "status": "needs_rebuild",
            "embedding_model": embedding_model,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "doc_count": 0,
            "chunk_count": 0,
            "built_at": None,
            "sha256": "",
        }
    task_id = str(latest["task_id"])
    chunks = state.list_chunks(user_id, task_id)
    doc_ids = {row["doc_id"] for row in chunks}
    return {
        "status": "ready" if chunks else "needs_rebuild",
        "embedding_model": embedding_model,
        "chunk_size": int(latest.get("chunk_size", chunk_size)),
        "overlap": int(latest.get("overlap", overlap)),
        "doc_count": len(doc_ids),
        "chunk_count": len(chunks),
        "built_at": latest["finished_at"],
        "sha256": "",
    }


def drop_task(user_id: int, task_id: str) -> None:
    """删除某任务在向量库里的切片（资料被删或重建前清理旧产物）。"""
    runtime.store().delete_task(user_id, task_id)


def drop_user(user_id: int) -> None:
    """删除某用户在向量库里的全部切片。"""
    runtime.store().delete_user(user_id)


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_OVERLAP",
    "SCORE_STAGES",
    "build_chunks",
    "context_citations",
    "drop_task",
    "drop_user",
    "index_manifest",
    "prompt",
    "retrieve",
    "retrieve_data",
    "run_ingest",
    "runtime",
    "task_chunks",
]
