"""Reciprocal Rank Fusion，自实现、零额外依赖。

公式：rrf(chunk) = Σ_route 1 / (k + rank_route(chunk))，默认 k=60。
每路必须先按该路分数降序；名次从 1 开始，未进入该路 top-N 的切片不计分。

并列 tie-break（与 retriever、pipeline 的排序约定一致）：
1. 同路原始分并列时按 chunk_id 字典序确定名次，不使用「并列同名次」，
   使同一输入在不同 Python 版本、不同路上线顺序下结果稳定；
2. 融合分并列时按 chunk_id 字典序；
3. 同一切片在两路都出现时，两路 RRF 分相加，不去重前截断。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

RRF_K = 60


def reciprocal_rank_fusion(
    routes: Iterable[Sequence[dict[str, Any]]],
    *,
    k: int = RRF_K,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if k <= 0:
        raise ValueError("RRF 的 k 必须大于 0")
    fused: dict[str, dict[str, Any]] = {}
    for route_index, route in enumerate(routes):
        ranked = sorted(route, key=lambda row: (-float(row.get("score", 0.0)), str(row["chunk_id"])))
        for rank, row in enumerate(ranked, start=1):
            chunk_id = str(row["chunk_id"])
            contribution = 1.0 / (k + rank)
            if chunk_id not in fused:
                fused[chunk_id] = {**row, "score": 0.0, "rrf_score": 0.0, "route_scores": {}}
            fused[chunk_id]["score"] += contribution
            fused[chunk_id]["rrf_score"] += contribution
            fused[chunk_id]["route_scores"][str(route_index)] = {
                "rank": rank,
                "contribution": contribution,
            }
    result = sorted(fused.values(), key=lambda row: (-row["rrf_score"], row["chunk_id"]))
    for row in result:
        row["score"] = row["rrf_score"]
    return result[: max(0, limit)]
