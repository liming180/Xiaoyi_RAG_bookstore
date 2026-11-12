r"""RETRIEVAL_REWRITE 端到端：两轮对话的第二轮必须被改写后再检索（N6 收口，施工单 §11.6 遗留）。

为什么这条不能只写单测：改写质量是「模型 + 提示词 + 历史拼接」三者合起来的事，
`test_rerank.py` 里已有的几条只验**降级路径**（超时 / 无历史 / 失败回原问题），
没有任何一条验「真的改写成功了、而且改写后的查询能命中正确资料」。
少了这条，「多轮指代消解」就只是代码里存在、线上没人证明它好使。

**断言走进程内，不走 HTTP**：`POST /internal/v1/retrieve` 只回 `citations` 与 `rows`
（`InternalRetrieveResult` 是 `additionalProperties: false`），诊断信息
（`originalQuestion` / `rewrittenQuestion` / `rewriteDegraded`）只存在于进程内的
`RecallResult.diagnostics`。所以建库走 HTTP、检索走 `ingest.retrieve(...)` 直调。

**为什么标记 live 并在 mock 档 skip**：`QueryRewriter.rewrite()` 顶部的
`if not history or ai_provider != "real" or not retrieval_rewrite: return question`
决定了 mock 档**根本不会发改写请求**。mock 档跑这条等于断言「原样返回原问题」——
那会绿，但它证明的是「没用」，不是「能用」。所以这里明确 skip 并写出原因，
另有一条 `test_mock_provider_skips_rewrite_by_design` 在 mock 档跑，钉住那个 skip 的理由是真的。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "assets" / "data"
sys.path.insert(0, str(ROOT))

from ai_app_loader import load_app

pytestmark = pytest.mark.live

CORPUS = [
    ("01_活动说明.md", "book-01"),
    ("02_借阅规则.md", "book-02"),
    ("03_空间预约.md", "book-03"),
    ("04_期刊与工具书.md", "book-04"),
    ("05_活动调整通知.md", "book-05"),
]

#: 第一轮问「几本」，第二轮只问「那借期呢」——第二轮脱离上下文无法独立检索。
FIRST_QUESTION = "普通图书最多借几本？"
FOLLOW_UP = "那借期呢？"
EXPECTED_DOC = "02_借阅规则.md"

TOKEN = "n6-token"
USER = 62

REQUIRED_ENV = (
    "EMBEDDING_ENDPOINT",
    "EMBEDDING_MODEL",
    "EMBEDDING_API_KEY",
    "LLM_ENDPOINT",
    "LLM_MODEL",
)


def _provider() -> str:
    return os.environ.get("AI_PROVIDER", "mock").strip().lower()


def _skip_reason() -> str:
    """返回空串表示可以跑；否则返回给人看的跳过原因。"""
    if _provider() != "real":
        return (
            f"需要真实 provider（当前 AI_PROVIDER={_provider() or '未设'}）："
            "QueryRewriter 在 mock 档按设计直接返回原问题，跑这一条只能证明「没用」"
        )
    missing = [key for key in REQUIRED_ENV if not os.environ.get(key, "").strip()]
    if missing:
        return "AI_PROVIDER=real 但缺少环境变量：" + "、".join(missing)
    return ""


_SKIP = _skip_reason()
_needs_real = pytest.mark.skipif(bool(_SKIP), reason=_SKIP or "")


@pytest.fixture()
def module(tmp_path, monkeypatch) -> Iterator[object]:
    """真实 provider 装配：保留调用方环境里的 provider 配置，只隔离存储与阶段节拍。"""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    monkeypatch.setenv("MILVUS_URI", "")  # 内存向量库，避免用例之间互相污染集合
    monkeypatch.setenv("RETRIEVAL_REWRITE", "true")
    yield load_app(monkeypatch, TOKEN)


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


@pytest.fixture()
def indexed(client) -> str:
    """一次提交全部语料：检索只认最近一次成功任务，分多次提交会只剩最后一份。"""
    documents = [
        {
            "doc_id": doc_id,
            "name": filename,
            "title": filename,
            "text": (DATA / filename).read_text(encoding="utf-8"),
        }
        for filename, doc_id in CORPUS
    ]
    headers = {"X-Internal-Token": TOKEN, "X-User-Id": str(USER)}
    resp = client.post(
        "/internal/v1/documents/parse",
        headers=headers,
        json={
            "documents": documents,
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-n6-rewrite",
            "generation": "g-1",
            # 摘要卡要再发一次 LLM 请求，与改写无关；关掉让这条用例只测一件事。
            "gen_summary": False,
        },
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["data"]["task_id"]

    task = client.get(f"/internal/v1/ingest/{task_id}", headers=headers).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def _recall(question: str, history: list[dict[str, str]], k: int = 3):
    """直调 `ingest.retrieve`，拿带 diagnostics 的 RecallResult。"""
    from app.schemas.models import RetrieveRequest
    from app.services import ingest

    return ingest.retrieve(
        USER,
        RetrieveRequest(question=question, k=k),
        history=history,
        mode="hybrid",
    )


def _titles(result) -> list[str]:
    return [item["doc_title"] for item in result.citations]


@_needs_real
def test_follow_up_is_rewritten_and_hits_the_right_document(indexed) -> None:
    """第二轮「那借期呢？」：改写结果 ≠ 原问题，且引用命中 02_借阅规则.md。"""
    first = _recall(FIRST_QUESTION, history=[])
    assert first.diagnostics["rewrittenQuestion"] == FIRST_QUESTION, (
        "第一轮没有历史，不该改写：" + str(first.diagnostics)
    )
    assert EXPECTED_DOC in _titles(first), _titles(first)

    history = [
        {"role": "user", "content": FIRST_QUESTION},
        {"role": "assistant", "content": "普通图书最多同时借阅 4 本。"},
    ]
    second = _recall(FOLLOW_UP, history=history)

    diagnostics = second.diagnostics
    assert diagnostics["originalQuestion"] == FOLLOW_UP, diagnostics
    assert diagnostics["rewrittenQuestion"] != FOLLOW_UP, (
        "第二轮必须被改写，否则「那借期呢」这种问题无法独立检索：" + str(diagnostics)
    )
    assert diagnostics["rewriteDegraded"] is False, (
        "改写失败会退化成原问题，这条要证明的是改写成功，不是降级：" + str(diagnostics)
    )
    assert 0 < len(diagnostics["rewrittenQuestion"]) <= 500, diagnostics
    assert EXPECTED_DOC in _titles(second), (
        "改写后的查询要能命中借阅规则：" + str(_titles(second))
    )


@_needs_real
def test_rewrite_keeps_borrowing_terms(indexed) -> None:
    """改写只做指代消解，不得把「借」「4 本 / 借期 / 21 天」这类线索全丢掉。"""
    history = [
        {"role": "user", "content": FIRST_QUESTION},
        {"role": "assistant", "content": "普通图书最多同时借阅 4 本。"},
    ]
    second = _recall(FOLLOW_UP, history=history)
    rewritten = second.diagnostics["rewrittenQuestion"]

    assert "借" in rewritten, f"改写丢了主题词：{rewritten}"
    assert any(token in rewritten for token in ("4", "四", "借期", "21")), (
        f"改写后的查询既没有「4 本」也没有「借期 / 21 天」，无法定位借阅规则：{rewritten}"
    )


def test_mock_provider_skips_rewrite_by_design(indexed) -> None:
    """mock 档不改写是**设计**，不是缺陷 —— 这条钉住上面 skipif 的理由是真的。

    若哪天有人给 mock 档也接上改写，这条会失败，提醒把上面两条 live 用例的 skip 条件
    一起改掉，而不是让它们继续无声地跳过。
    """
    if _provider() == "real":
        pytest.skip("real 档跑这条没有意义：改写本来就该发生")

    history = [{"role": "user", "content": FIRST_QUESTION}]
    second = _recall(FOLLOW_UP, history=history)

    assert second.diagnostics["rewrittenQuestion"] == FOLLOW_UP, second.diagnostics
    assert second.diagnostics["rewriteDegraded"] is False, (
        "mock 档不是「改写失败」，是「压根没发请求」：" + str(second.diagnostics)
    )


def test_rewrite_is_off_without_history(indexed) -> None:
    """没有历史就不该发改写请求（省一次 LLM 调用），两档都成立。"""
    result = _recall(FIRST_QUESTION, history=[])
    assert result.diagnostics["rewrittenQuestion"] == FIRST_QUESTION, result.diagnostics
    assert result.diagnostics["rewriteDegraded"] is False, result.diagnostics
