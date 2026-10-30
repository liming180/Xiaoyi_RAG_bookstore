"""相似度与检索：cosine / select_top_k / rank_all（对应 F5 / F7 / F8）。"""
from __future__ import annotations

import math
from typing import Any

from .settings import AppError


def cosine(a: list[float], b: list[float]) -> float:
    """先按最大绝对值缩放再归一化，避免 1e308 级数值溢出。"""
    if not a or not b or len(a) != len(b):
        raise AppError("向量维度不一致，无法计算相似度。")
    scale_a = max(abs(v) for v in a)
    scale_b = max(abs(v) for v in b)
    if scale_a == 0 or scale_b == 0:
        raise AppError("向量全为零，无法计算相似度。")
    scaled_a = [v / scale_a for v in a]
    scaled_b = [v / scale_b for v in b]
    norm_a = math.sqrt(math.fsum(v * v for v in scaled_a))
    norm_b = math.sqrt(math.fsum(v * v for v in scaled_b))
    score = math.fsum((x / norm_a) * (y / norm_b) for x, y in zip(scaled_a, scaled_b))
    if not math.isfinite(score):
        raise AppError("无法计算有效相似度，请检查嵌入向量。")
    return max(-1.0, min(1.0, score))


def _scored(chunks: list[dict[str, Any]], query_vector: list[float]) -> list[dict[str, Any]]:
    """在副本上打分，绝不修改原 chunks 的顺序。"""
    return [dict(chunk, score=cosine(query_vector, chunk["embedding"])) for chunk in chunks]


def select_top_k(chunks: list[dict[str, Any]], query_vector: list[float], k: int) -> list[dict[str, Any]]:
    """按 score 从大到小排序后取前 k 条（学生任务一的正解）。"""
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise AppError("k 须为不小于 1 的整数。")
    scored = _scored(chunks, query_vector)
    scored.sort(key=lambda chunk: (-chunk["score"], chunk["chunk_id"]))
    return scored[:k]


def rank_all(chunks: list[dict[str, Any]], query_vector: list[float]) -> list[dict[str, Any]]:
    """返回全部片段带 rank 的全量 trace —— F8 的检索过程表数据源。"""
    trace = _scored(chunks, query_vector)
    trace.sort(key=lambda chunk: (-chunk["score"], chunk["chunk_id"]))
    for position, chunk in enumerate(trace, 1):
        chunk["rank"] = position
    return trace


def split_trace(trace: list[dict[str, Any]], k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 k 切出取回片段，并给全量 trace 打上 retrieved 标记（取回界线）。"""
    hits = trace[:k]
    for chunk in trace:
        chunk["retrieved"] = chunk["rank"] <= k
    return hits, trace


def public_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剥离 embedding，供界面与日志使用。"""
    return [
        {key: value for key, value in hit.items() if key != "embedding"}
        for hit in hits
    ]
