"""A3 四档对照与真实堆栈验证。

三档本地（dense/bm25/rrf/hybrid）在 TestClient 上跑，
确认配置切换、轨迹形状与「引用数随 k 变、轨迹不缩」。
真实堆栈（容器栈 + 智谱 embedding）由 test-artifacts/_probe_a3_stack.py 一次性验证，
不进版本库，与本文件并行跑。
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "assets" / "data"
sys.path.insert(0, str(ROOT))

from ai_app_loader import load_app

CORPUS = [
    ("01_活动说明.md", "book-01"),
    ("02_借阅规则.md", "book-02"),
    ("03_空间预约.md", "book-03"),
    ("04_期刊与工具书.md", "book-04"),
    ("05_活动调整通知.md", "book-05"),
]


@pytest.fixture()
def module(tmp_path, monkeypatch) -> Iterator[object]:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    monkeypatch.setenv("MILVUS_URI", "")
    yield load_app(monkeypatch, "a3-token")


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


@pytest.fixture()
def indexed(client, module) -> dict[int, str]:
    """一次提交全部语料：检索只认最近一次成功任务，分多次提交会只剩最后一份。"""
    documents = []
    for filename, doc_id in CORPUS:
        content = (DATA / filename).read_bytes()
        documents.append({
            "doc_id": doc_id,
            "name": filename,
            "title": filename,
            "text": content.decode("utf-8"),
        })

    resp = client.post(
        "/internal/v1/documents/parse",
        headers={"X-Internal-Token": "a3-token", "X-User-Id": "2"},
        json={
            "documents": documents,
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-a3",
            "generation": "g-1",
        },
    )
    assert resp.status_code == 200, resp.text

    task_id = resp.json()["data"]["task_id"]
    task = client.get(
        f"/internal/v1/ingest/{task_id}",
        headers={"X-Internal-Token": "a3-token", "X-User-Id": "2"},
    ).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return {"task_id": task_id, "docs": [doc_id for _, doc_id in CORPUS]}


def _retrieve(client, question: str, mode: str, k: int = 5, user: int = 2):
    resp = client.post(
        "/internal/v1/retrieve",
        headers={"X-Internal-Token": "a3-token", "X-User-Id": str(user)},
        json={"question": question, "k": k, "mode": "rag", "history": []},
        params={"retrieval_mode": mode},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_trace_row_matches_contract_without_score_stage(client, indexed) -> None:
    """InternalTraceRow 是 additionalProperties:false 且没有 score_stage。"""
    data = _retrieve(client, "普通图书最多借几本", "dense")
    expected = {
        "rank", "chunk_id", "doc_id", "doc_title", "heading_path", "excerpt",
        "start", "end", "score", "retrieved", "kind", "verified",
    }
    for row in data["rows"]:
        assert set(row) == expected, row
    assert [row["rank"] for row in data["rows"]] == list(range(1, len(data["rows"]) + 1))


def test_dense_mode_shape(client, indexed) -> None:
    data = _retrieve(client, "普通图书最多借几本", "dense")
    assert data["citations"]
    assert data["rows"]
    # dense 档只有向量路：引用与轨迹同源，档位标在 citations 上
    assert all(item["score_stage"] == "dense" for item in data["citations"])
    assert len(data["citations"]) <= 5


def test_bm25_mode_shape(client, indexed) -> None:
    data = _retrieve(client, "普通图书最多借几本", "bm25")
    assert data["citations"]
    assert all(item["score_stage"] == "sparse" for item in data["citations"])


def test_rrf_mode_shape(client, indexed) -> None:
    data = _retrieve(client, "普通图书最多借几本", "rrf")
    assert data["citations"]
    assert all(item["score_stage"] == "rrf" for item in data["citations"])


def test_hybrid_mode_shape(client, indexed) -> None:
    data = _retrieve(client, "普通图书最多借几本", "hybrid")
    assert data["citations"]
    # hybrid 走 rerank，引用档位是 rerank
    assert all(item["score_stage"] == "rerank" for item in data["citations"])


def test_hybrid_has_candidates_and_retrieved_boundary(client, indexed) -> None:
    data = _retrieve(client, "普通图书最多借几本，借期多久？", "hybrid", k=3)
    rows = data["rows"]
    assert len(rows) >= 3
    assert len(data["citations"]) == 3
    # retrieved 标记必须存在，且前 k 个一定是 True（它们进了生成上下文）
    assert all(row["retrieved"] for row in rows[:3])
    # 后续候选可以是 True 也可以是 False，但字段必须存在
    for row in rows[3:]:
        assert "retrieved" in row
        assert isinstance(row["retrieved"], bool)


def test_hybrid_diagnostics_stay_out_of_http_response(client, indexed, module) -> None:
    """诊断信息只在进程内，HTTP 响应必须严格等于契约的两个字段。"""
    data = _retrieve(client, "普通图书最多借几本", "hybrid")
    assert set(data) == {"citations", "rows"}, data

    from app.schemas.models import RetrieveRequest
    from app.services import ingest

    result = ingest.retrieve(2, RetrieveRequest(question="普通图书最多借几本", k=3), mode="hybrid")
    diag = result.diagnostics
    assert diag["mode"] == "hybrid"
    assert diag["originalQuestion"] == "普通图书最多借几本"
    assert "rewrittenQuestion" in diag
    assert "rewriteDegraded" in diag
    assert len(diag["dense"]) > 0
    assert len(diag["sparse"]) > 0
    assert len(diag["rrf"]) > 0
    assert len(diag["rerank"]) > 0
    assert "rerankDegraded" in diag
    assert "degradeReason" in diag
    # 每一路候选都要带 chunkId 与分数，便于对照淘汰位置
    for route in ("dense", "sparse", "rrf", "rerank"):
        assert all({"chunkId", "score"} <= set(item) for item in diag[route]), route


def test_cross_user_returns_no_citations(client, indexed) -> None:
    resp = client.post(
        "/internal/v1/retrieve",
        headers={"X-Internal-Token": "a3-token", "X-User-Id": "1"},
        json={"question": "普通图书最多借几本", "mode": "rag", "k": 3, "history": []},
        params={"retrieval_mode": "hybrid"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 用户 1 没建过库，应该没有引用
    assert data["citations"] == []
    assert data["rows"] == []
