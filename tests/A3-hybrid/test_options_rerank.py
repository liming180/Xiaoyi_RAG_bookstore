"""N1：参数实验的 `rerank` 轴必须真的改变检索结果。

背景（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §3.1）：修这个缺陷之前，
`ExperimentServiceImpl` 只把 `k` 传给评测，`rerank` / `chunkSize` / `overlap` / `summary`
写进 `params_json` 落库后无人读取；`InternalChatRequest` 也没有 `options` 字段
（`additionalProperties: false`），Python 侧 `ChatRequest` 更是没有这个属性 ——
Pydantic 静默丢弃，于是「rerank=true / false」两组跑出来完全一样。

本文件验的是链条的后半段（Python）：`options.rerank` 一路传到 `ingest.retrieve`，
`false` 时引用里不出现 `score_stage=rerank`，`true` 时出现。前半段（Java 侧
camelCase → snake_case 的 `options` 映射）由 `EvalServiceOptionsTest` 覆盖。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "assets" / "data"

CORPUS = [
    ("01_活动说明.md", "book-01"),
    ("02_借阅规则.md", "book-02"),
    ("03_空间预约.md", "book-03"),
]

TOKEN = "n1-token"
USER = 41


@pytest.fixture()
def module(tmp_path, monkeypatch) -> Iterator[object]:
    from ai_app_loader import load_app

    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    monkeypatch.setenv("MILVUS_URI", "")
    # 全局默认开着重排，这样「rerank=false 覆盖全局」才有东西可覆盖。
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("RETRIEVAL_RERANK", "true")
    yield load_app(monkeypatch, TOKEN)


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


@pytest.fixture()
def indexed(client) -> str:
    """一次提交全部语料：检索只认最近一次成功任务。"""
    documents = []
    for filename, doc_id in CORPUS:
        documents.append(
            {
                "doc_id": doc_id,
                "name": filename,
                "title": filename,
                "text": (DATA / filename).read_text(encoding="utf-8"),
            }
        )
    headers = {"X-Internal-Token": TOKEN, "X-User-Id": str(USER)}
    resp = client.post(
        "/internal/v1/documents/parse",
        headers=headers,
        json={
            "documents": documents,
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-n1",
            "generation": "g-1",
        },
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["data"]["task_id"]
    task = client.get(f"/internal/v1/ingest/{task_id}", headers=headers).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def _chat(client, question: str, options: dict | None = None) -> list[dict]:
    """跑一次 SSE，返回 retrieval 帧里的 citations。"""
    body: dict = {"question": question, "history": [], "mode": "rag", "k": 3}
    if options is not None:
        body["options"] = options
    resp = client.post(
        "/internal/v1/chat/stream",
        headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
        json=body,
    )
    assert resp.status_code == 200, resp.text
    citations: list[dict] = []
    for raw in resp.text.splitlines():
        if not raw.startswith("data: "):
            continue
        payload = json.loads(raw[6:])
        if "citations" in payload:
            citations = payload["citations"]
    return citations


def test_chat_request_accepts_options_without_extra_forbid(client) -> None:
    """契约里 options 是显式声明的可选对象；Pydantic 必须收下，不能静默丢弃。"""
    from app.schemas.models import ChatRequest

    parsed = ChatRequest.model_validate(
        {"question": "普通图书最多借几本", "options": {"rerank": False, "summary": True}}
    )
    assert parsed.options == {"rerank": False, "summary": True}


def test_rerank_false_skips_rerank_stage(client, indexed) -> None:
    citations = _chat(client, "普通图书最多借几本，借期多久？", {"rerank": False})
    assert citations, "建库后应当有引用"
    assert all(item["score_stage"] != "rerank" for item in citations), citations
    # 跳过精排后走融合顺序，档位是 rrf。
    assert all(item["score_stage"] == "rrf" for item in citations), citations


def test_rerank_true_keeps_rerank_stage(client, indexed) -> None:
    citations = _chat(client, "普通图书最多借几本，借期多久？", {"rerank": True})
    assert citations
    assert all(item["score_stage"] == "rerank" for item in citations), citations


def test_absent_option_falls_back_to_global_setting(client, indexed) -> None:
    """不传 options 时沿用 RETRIEVAL_RERANK=true，行为与 A3 完全一致。"""
    citations = _chat(client, "普通图书最多借几本，借期多久？", None)
    assert citations
    assert all(item["score_stage"] == "rerank" for item in citations), citations


def test_two_axis_values_produce_different_stages(client, indexed) -> None:
    """同一句话、只改 rerank 轴，两组的档位必须不同 —— 这是「轴真生效」的判据。"""
    off = _chat(client, "普通图书最多借几本，借期多久？", {"rerank": False})
    on = _chat(client, "普通图书最多借几本，借期多久？", {"rerank": True})
    assert {item["score_stage"] for item in off} != {item["score_stage"] for item in on}


def test_diagnostics_records_effective_rerank(client, indexed, module) -> None:
    """诊断里记下本次实际生效的开关，便于报告与排障。"""
    from app.schemas.models import RetrieveRequest
    from app.services import ingest

    result = ingest.retrieve(USER, RetrieveRequest(question="普通图书最多借几本", k=3), rerank=False)
    assert result.diagnostics["rerankRequested"] is False
    assert result.diagnostics["rerankEffective"] is False

    result = ingest.retrieve(USER, RetrieveRequest(question="普通图书最多借几本", k=3), rerank=None)
    assert result.diagnostics["rerankRequested"] is None
    assert result.diagnostics["rerankEffective"] is True
