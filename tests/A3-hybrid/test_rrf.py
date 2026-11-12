"""RRF 的分数、双路加分与确定性 tie-break 的手算对照。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server-ai"))

from app.core.rag.fusion import reciprocal_rank_fusion


def row(chunk_id: str, score: float) -> dict:
    return {"chunk_id": chunk_id, "score": score, "excerpt": chunk_id}


def test_rrf_scores_match_hand_calculation() -> None:
    dense = [row("D01-C001", 0.9), row("D02-C001", 0.8), row("D03-C001", 0.7)]
    sparse = [row("D02-C001", 8.0), row("D04-C001", 6.0), row("D01-C001", 4.0)]

    result = reciprocal_rank_fusion((dense, sparse), k=60, limit=20)
    scores = {item["chunk_id"]: item["rrf_score"] for item in result}

    assert scores["D01-C001"] == pytest.approx(1 / 61 + 1 / 63)
    assert scores["D02-C001"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["D03-C001"] == pytest.approx(1 / 63)
    assert scores["D04-C001"] == pytest.approx(1 / 62)
    assert [item["chunk_id"] for item in result] == [
        "D02-C001", "D01-C001", "D04-C001", "D03-C001",
    ]


def test_rrf_tie_break_uses_chunk_id_not_input_order() -> None:
    # 每个分块只出现在一路（rank1=1/61），融合分相同；字典序 D01 必须在 D02 前，与传入顺序无关。
    forward = reciprocal_rank_fusion(([row("D02-C001", 1.0)], [row("D01-C001", 1.0)]))
    reverse = reciprocal_rank_fusion(([row("D01-C001", 1.0)], [row("D02-C001", 1.0)]))
    assert [item["chunk_id"] for item in forward] == ["D01-C001", "D02-C001"]
    assert [item["chunk_id"] for item in reverse] == ["D01-C001", "D02-C001"]
    assert all(item["rrf_score"] == pytest.approx(1 / 61) for item in forward)


def test_rrf_tie_within_route_gets_stable_distinct_ranks() -> None:
    # 同路同分不共享 rank：D01 是 rank1=1/61，D02 是 rank2=1/62。
    result = reciprocal_rank_fusion(([row("D02-C001", 0.5), row("D01-C001", 0.5)],), limit=2)
    assert [item["chunk_id"] for item in result] == ["D01-C001", "D02-C001"]
    assert result[0]["rrf_score"] == pytest.approx(1 / 61)
    assert result[1]["rrf_score"] == pytest.approx(1 / 62)


def test_rrf_limit_is_applied_after_deduplication() -> None:
    result = reciprocal_rank_fusion(
        ([row("D01-C001", 0.9)], [row("D01-C001", 8.0), row("D02-C001", 7.0)]), limit=2,
    )
    assert len(result) == 2
    assert result[0]["chunk_id"] == "D01-C001"


def test_rrf_rejects_non_positive_k() -> None:
    with pytest.raises(ValueError, match="必须大于 0"):
        reciprocal_rank_fusion([], k=0)
