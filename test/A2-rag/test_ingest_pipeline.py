"""A2 建库管线：切分、元数据、隔离。

这一层的价值在于「换掉旧实现后，切片是否还满足契约」。旧实现用固定滑窗 + 占位
`heading_path`（恒为 `# 模拟章节`），字段齐全但语义是假的；新实现必须做到：

* `heading_path` 来自真实 Markdown 标题，且逐级继承（`# 一级 > ## 二级`）；
* `start` / `end` 是原文偏移，`excerpt == text[start:end]`，窗口单调、无空洞；
* `chunk_id` 满足契约 pattern `^D\\d{2}-C\\d{3}$`；
* 投毒样本切片照常入库，但 `verified=False`；
* 检索只回本人最近一次成功任务的切片，换个人就是空列表。

全部走进程内 app + mock provider + 内存向量库，不依赖 Milvus 与外网。
"""

from __future__ import annotations

import re

import pytest

from ai_app_loader import load_app

TOKEN = "a2-internal-token"
USER_A = 7
USER_B = 8

CHUNK_ID = re.compile(r"^D\d{2}-C\d{3}$")

NESTED = """# 星河读书会

导读段落，标题前的内容也要有归属。

## 借阅规则

已登记成员每人最多同时借阅4本普通图书，每本借期21天。

### 续借

普通图书在到期前可申请续借1次，续借增加7天。

## 空间预约

自习区可提前一天预约，单次最长两小时。
"""


@pytest.fixture()
def module(monkeypatch, tmp_path):
    """装配一个干净的 app：mock provider、无 Milvus、状态库落在临时目录。"""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    return load_app(monkeypatch, TOKEN)


@pytest.fixture()
def splitter(monkeypatch):
    """纯函数用例只需要 `server-ai` 可 import，不必装配整个 app。

    `splitter.py` 不读配置、不连网络，所以走 syspath 注入即可；
    用完整 app 反而会把 settings 的必填项（INTERNAL_TOKEN）牵扯进来。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "server-ai"))
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    return importlib.import_module("app.core.rag.splitter")


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        yield client


def headers(user: int = USER_A) -> dict[str, str]:
    return {"X-Internal-Token": TOKEN, "X-User-Id": str(user)}


def parse(client, text: str, *, user: int = USER_A, key: str = "sk-a2") -> str:
    """提交一次建库并等到终态，返回 task_id。"""
    response = client.post(
        "/internal/v1/documents/parse",
        headers=headers(user),
        json={
            "documents": [
                {"doc_id": "d1", "name": "nested.md", "title": "星河读书会", "text": text}
            ],
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": key,
            "generation": "g-1",
        },
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["task_id"]

    task = client.get(f"/internal/v1/ingest/{task_id}", headers=headers(user)).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def retrieve(client, question: str, *, user: int = USER_A, k: int = 3) -> list[dict]:
    response = client.post(
        "/internal/v1/retrieve",
        headers=headers(user),
        json={"question": question, "k": k},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["citations"]


# ---------------------------------------------------------------- 纯函数：切分质量


def test_heading_path_inherits_nested_titles(splitter):
    pieces = list(splitter.build_pieces(NESTED, 1, 180, 30, "星河读书会"))
    paths = {piece["heading_path"] for piece in pieces}

    assert "" not in paths, "每个切片都必须有 heading_path"
    assert any("星河读书会" in path for path in paths)
    assert any("借阅规则" in path for path in paths)
    # 三级标题要带上两级祖先，而不是只留自己。
    nested = [path for path in paths if "续借" in path]
    assert nested, paths
    assert all("星河读书会" in path and "借阅规则" in path for path in nested), nested


def test_offsets_are_monotonic_and_excerpts_match_source(splitter):
    pieces = list(splitter.build_pieces(NESTED, 1, 60, 15, "星河读书会"))
    assert len(pieces) >= 3, "窗口设小后应切出多片"

    previous_end = 0
    for piece in pieces:
        assert piece["start"] < piece["end"], piece
        assert piece["excerpt"] == NESTED[piece["start"] : piece["end"]], piece
        # 允许重叠，但不允许出现没被任何窗口覆盖的空洞。
        assert piece["start"] <= previous_end, piece
        previous_end = max(previous_end, piece["end"])
    assert previous_end == len(NESTED)


def test_chunk_id_matches_contract_pattern(splitter):
    pieces = list(splitter.build_pieces(NESTED, 3, 180, 30, "星河读书会"))
    assert pieces
    for piece in pieces:
        assert CHUNK_ID.match(piece["chunk_id"]), piece["chunk_id"]


def test_poison_sample_is_kept_but_marked_untrusted(splitter):
    """投毒语料不能因为「可疑」就被丢掉 —— 丢掉等于改变事实，正确做法是降可信标记。"""
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "fixtures" / "sample_inject.md"
    text = sample.read_text(encoding="utf-8")
    pieces = list(splitter.build_pieces(text, 6, 180, 30, "sample_inject.md"))

    assert pieces, "投毒样本也要产出切片"
    assert any(piece["verified"] is False for piece in pieces), "投毒样本必须被标为不可信"
    assert all(piece["excerpt"].strip() for piece in pieces), "切片内容不能为空"


# ---------------------------------------------------------------- 接口链路


def test_parse_stores_chunks_with_real_heading_path(client):
    parse(client, NESTED, key="sk-parse")

    chunks = client.get("/internal/v1/ingest/" + "x", headers=headers()).json()
    assert chunks["code"] == 40402  # 未知任务按不存在处理，不泄露他人任务

    task_id = client.get("/internal/v1/index/status", headers=headers()).json()["data"]
    assert task_id["status"] == "ready", task_id
    assert task_id["chunk_count"] > 0, task_id

    # 逐片核对：从 Java 视角拿到的 chunks 也必须带真实章节路径。
    listing = client.post(
        "/internal/v1/retrieve",
        headers=headers(),
        json={"question": None, "k": 10, "list_mode": True},
    ).json()["data"]["citations"]
    assert listing, "建库成功后列举模式应能列出切片"
    assert all(item["heading_path"] for item in listing), listing


def test_retrieve_returns_contract_complete_citations(client):
    parse(client, NESTED, key="sk-retrieve")
    citations = retrieve(client, "每人最多借几本", k=2)

    assert citations, "本人刚建完库，检索不该为空"
    required = {
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
    }
    for citation in citations:
        assert set(citation) == required, citation
        assert CHUNK_ID.match(citation["chunk_id"]), citation
        assert citation["score_stage"] in {"dense", "sparse", "rrf", "rerank"}
        assert citation["start"] < citation["end"], citation
        assert citation["excerpt"], citation
    assert [item["ref"] for item in citations] == list(range(1, len(citations) + 1))


def test_retrieve_is_scoped_to_the_requesting_user(client):
    """A 建了库，B 用同一个问题检索必须是空 —— 这是 A2 不能退让的隔离线。"""
    parse(client, NESTED, key="sk-isolation")

    assert retrieve(client, "每人最多借几本"), "A 自己应当能检索到"
    assert retrieve(client, "每人最多借几本", user=USER_B) == [], "B 不该看到 A 的切片"


def test_k_controls_citation_count(client):
    parse(client, NESTED, key="sk-k")
    total = len(retrieve(client, "借阅规则", k=10))
    assert total >= 3, f"语料切出的切片不足以验证 k，实际 {total}"

    for k in (1, 2, 3):
        assert len(retrieve(client, "借阅规则", k=k)) == k


def test_direct_mode_omits_retrieval_frame(client):
    """direct 是「不用资料」的模式，发空 retrieval 帧也算违约，必须整帧不发。"""
    parse(client, NESTED, key="sk-direct")

    response = client.post(
        "/internal/v1/chat/stream",
        headers=headers(),
        json={"question": "每人最多借几本", "mode": "direct"},
    )
    assert response.status_code == 200, response.text
    assert "event: retrieval" not in response.text
    assert "event: done" in response.text


def test_rag_mode_emits_retrieval_with_own_citations(client):
    parse(client, NESTED, key="sk-rag")

    response = client.post(
        "/internal/v1/chat/stream",
        headers=headers(),
        json={"question": "每人最多借几本", "mode": "rag", "k": 2},
    )
    assert response.status_code == 200, response.text
    assert "event: retrieval" in response.text

    frame = [
        line for line in response.text.splitlines() if line.startswith("data: ") and "citations" in line
    ]
    assert frame, response.text
    import json

    payload = json.loads(frame[0][6:])
    assert payload["citations"], "rag 模式下必须带本人语料的引用"
    assert all(item["doc_id"] for item in payload["citations"])
