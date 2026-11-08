"""检索管线：查询改写（可选）→ 纯向量召回 → 拼装引用与轨迹。

A2 阶段只做纯向量 top-k；A3 会在这里挂 BM25 与 RRF，所以召回入口固定为
`recall()`，返回结构里预留 `score_stage`，由后续阶段改写。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..vector_store.store import VectorStore

# 引用必须有的字段，与 InternalCitation.required 完全一致。
CITATION_FIELDS: tuple[str, ...] = (
    "ref",
    "chunk_id",
    "doc_id",
    "doc_title",
    "heading_path",
    "excerpt",
    "start",
    "end",
    "score",
    "score_stage",
    "kind",
    "verified",
)


@dataclass
class RecallRequest:
    """一次检索的输入。"""

    user_id: int
    task_id: str
    vector: Sequence[float]
    k: int = 3
    doc_ids: list[str] = field(default_factory=list)
    kind: str | None = None


@dataclass
class RecallResult:
    """检索输出：引用 + 轨迹，字段与内部契约对齐。"""

    citations: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    elapsed_ms: int


def _as_citation(ref: int, hit: dict[str, Any], stage: str) -> dict[str, Any]:
    """把检索命中整理成 InternalCitation；缺字段直接报错而不是悄悄补默认值。"""
    citation = {
        "ref": ref,
        "chunk_id": hit["chunk_id"],
        "doc_id": hit["doc_id"],
        "doc_title": hit.get("doc_title", ""),
        "heading_path": hit.get("heading_path", ""),
        "excerpt": hit.get("excerpt", ""),
        "start": int(hit.get("start", 0)),
        "end": int(hit.get("end", 0)),
        "score": float(hit.get("score", 0.0)),
        "score_stage": stage,
        "kind": hit.get("kind", "chunk"),
        "verified": bool(hit.get("verified", True)),
    }
    missing = [name for name in CITATION_FIELDS if name not in citation]
    if missing:
        raise ValueError(f"引用缺少契约字段：{missing}")
    return citation


def _as_trace_row(rank: int, hit: dict[str, Any], stage: str) -> dict[str, Any]:
    """轨迹行：引用字段去掉 `ref` 与 `score_stage`，再加 `rank` / `retrieved`。

    契约里 `InternalTraceRow` 与 `InternalCitation` 的字段集**不一样**：
    轨迹行没有 `ref`（它用 `rank`）也没有 `score_stage`，且 `additionalProperties: false`。
    多给一个字段不是「信息更全」，而是让整条轨迹在 Java 侧反序列化时被判为非法。
    """
    row = _as_citation(rank, hit, stage)
    row.pop("ref")
    row.pop("score_stage")
    row["rank"] = rank
    row["retrieved"] = True
    return row


def recall(store: VectorStore, request: RecallRequest, stage: str = "dense") -> RecallResult:
    """执行一次召回并组装引用与轨迹。"""
    started = time.perf_counter()
    hits = store.search(
        user_id=request.user_id,
        task_id=request.task_id,
        vector=request.vector,
        k=request.k,
        doc_ids=request.doc_ids,
        kind=request.kind,
    )
    citations = [_as_citation(index + 1, hit, stage) for index, hit in enumerate(hits)]
    rows = [_as_trace_row(index + 1, hit, stage) for index, hit in enumerate(hits)]
    elapsed = int((time.perf_counter() - started) * 1000)
    return RecallResult(citations=citations, rows=rows, elapsed_ms=elapsed)


def dedupe_by_chunk(citations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 chunk_id 去重并重排 ref，避免多路召回把同一切片塞两次。"""
    seen: dict[str, dict[str, Any]] = {}
    for citation in citations:
        seen.setdefault(citation["chunk_id"], citation)
    ordered = sorted(seen.values(), key=lambda item: (-item["score"], item["chunk_id"]))
    for index, citation in enumerate(ordered, start=1):
        citation["ref"] = index
    return ordered
