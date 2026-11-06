"""切片与任务推进：解析、切片、向量化、摘要四段进度，以及按用户范围检索。"""

from __future__ import annotations

import re
import time
from typing import Any

from ..config import get_settings
from ..schemas.models import ParseDocument, ParseRequest, RetrieveRequest
from . import state

# 单文档切片上限，保证 chunk_id 满足 ^D\d{2}-C\d{3}$ 契约。
MAX_CHUNKS_PER_DOC = 999
MAX_DOCS_PER_USER = 99
# 索引清单在无成功任务时回退到的默认切片参数。
DEFAULT_CHUNK_SIZE = 180
DEFAULT_OVERLAP = 30


def split_ranges(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    """按固定窗口切分文本，窗口之间保留 overlap 个字符的重叠。"""
    length = len(text)
    if length == 0:
        return [(0, 0)]
    step = max(1, chunk_size - max(0, overlap))
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while cursor < length and len(ranges) < MAX_CHUNKS_PER_DOC:
        end = min(length, cursor + chunk_size)
        ranges.append((cursor, end))
        if end >= length:
            break
        cursor += step
    return ranges


def _chunk_id(doc_no: int, index: int) -> str:
    """生成契约要求的切片编号。"""
    return f"D{doc_no:02d}-C{index:03d}"


def build_chunks(user_id: int, doc: ParseDocument, doc_no: int, req: ParseRequest) -> list[dict[str, Any]]:
    """把一份文档切成切片记录，字段与 Citation 契约一致。"""
    text = doc.text or doc.title or doc.name or ""
    title = doc.title or doc.name or doc.doc_id
    parts: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(split_ranges(text, req.chunk_size, req.overlap), start=1):
        excerpt = text[start:end] or "模拟片段"
        parts.append(
            {
                "chunk_id": _chunk_id(doc_no, index),
                "doc_id": doc.doc_id,
                "doc_title": title,
                "heading_path": "# 模拟章节",
                "excerpt": excerpt,
                "start": start,
                "end": end,
                "score": 0.9,
                "score_stage": "rerank",
                "kind": "chunk",
                "verified": True,
            }
        )
    return parts


def _pause() -> None:
    """阶段间停顿：让 Java 的轮询看得见完整阶段序列。

    `ingest_stage_delay_ms` 默认 0（全速）；门禁环境把它调到大于 Java 轮询间隔，
    否则五个阶段会在毫秒内跑完，轮询只能抓到 parsing 与 done。只影响观测粒度，不改结果。
    """
    delay_ms = get_settings().ingest_stage_delay_ms
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def run_ingest(user_id: int, task_id: str, req: ParseRequest) -> None:
    """后台推进一次解析任务；任何异常都把任务置为 FAILED。"""
    try:
        state.update_task(user_id, task_id, status="RUNNING", stage="parsing", progress=20)
        for doc in req.documents:
            state.upsert_document(user_id, doc.doc_id, doc.title or doc.name or doc.doc_id, "PARSING", 0)
        _pause()
        state.update_task(user_id, task_id, stage="splitting", progress=45)

        total = 0
        for doc in req.documents:
            doc_no = state.document_number(user_id, doc.doc_id)
            if doc_no <= 0 or doc_no > MAX_DOCS_PER_USER:
                doc_no = max(1, min(MAX_DOCS_PER_USER, doc_no or 1))
            parts = build_chunks(user_id, doc, doc_no, req)
            state.replace_chunks(user_id, task_id, doc.doc_id, parts)
            state.upsert_document(
                user_id,
                doc.doc_id,
                doc.title or doc.name or doc.doc_id,
                "INDEXED",
                len(parts),
            )
            total += len(parts)

        _pause()
        state.update_task(user_id, task_id, stage="embedding", progress=70, chunk_count=total)
        _pause()
        state.update_task(user_id, task_id, stage="summarizing", progress=90)
        _pause()
        state.update_task(
            user_id,
            task_id,
            status="SUCCEEDED",
            stage="done",
            progress=100,
            chunk_count=total,
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


def _score(question: str | None, excerpt: str, base: float) -> float:
    """按问题词命中率对基础分做加权，问题为空时直接用基础分。"""
    if not question:
        return round(base, 3)
    tokens = [token for token in re.findall(r"[0-9a-zA-Z_]+", question.lower()) if token]
    if not tokens:
        return round(base, 3)
    lowered = excerpt.lower()
    hits = sum(1 for token in tokens if token in lowered)
    return round(min(1.0, base * (0.5 + 0.5 * hits / len(tokens))), 3)


def scoped_chunks(user_id: int, req: RetrieveRequest) -> list[dict[str, Any]]:
    """取该用户最近一次成功任务的切片，按请求条件过滤后排序。"""
    latest = state.latest_succeeded_task(user_id)
    if latest is None:
        return []
    rows = state.list_chunks(user_id, str(latest["task_id"]))
    found = [
        row
        for row in rows
        if (not req.doc_ids or row["doc_id"] in req.doc_ids) and (not req.kind or row["kind"] == req.kind)
    ]
    for row in found:
        row["score"] = _score(req.question, row["excerpt"], float(row["score"]))
    found.sort(key=lambda row: (-row["score"], row["chunk_id"]))
    return found[: req.k]


def retrieve_data(user_id: int, req: RetrieveRequest) -> dict[str, Any]:
    """检索结果；无命中时返回空引用列表，不伪造引用。"""
    found = scoped_chunks(user_id, req)
    citations = [{"ref": index + 1, **row} for index, row in enumerate(found)]
    rows = [{"rank": index + 1, **row, "retrieved": True} for index, row in enumerate(found)]
    return {"citations": citations, "rows": rows}


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
