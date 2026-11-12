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

import importlib
import re
import time

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


# ---------------------------------------------------------------- 容量与主键
#
# 这两条是容器栈实测踩出来的：`local-a` 累计上传到 122 份资料后建库直接失败，
# 报 `MilvusException: duplicate primary keys are not allowed in the same batch`。
# 根因是 chunk_id 的文档号只有两位，第 100 份起被 clamp 成 D99，同批主键撞车。


def test_document_number_over_limit_fails_with_actionable_message(module):
    """99 个编号用满时必须报「上限」而不是悄悄截断成 D99。"""
    ingest = importlib.import_module("app.services.ingest")
    state = importlib.import_module("app.services.state")

    for index in range(99):
        state.upsert_document(USER_A, f"doc-{index}", f"资料 {index}", "INDEXED", 1)

    with pytest.raises(ValueError) as excinfo:
        state.upsert_document(USER_A, "doc-overflow", "第 100 份", "PARSING", 0)
    message = str(excinfo.value)
    assert "上限" in message and "99" in message, message
    assert "删除" in message, "报错要给出可执行动作"

    # 编号必须是 1..99 且不重复，不能像旧实现那样把超出的都压成 99。
    numbers = [
        state.document_number(USER_A, f"doc-{index}")
        for index in range(99)
        if state.document_number(USER_A, f"doc-{index}")
    ]
    assert sorted(numbers) == list(range(1, 100))
    assert ingest.MAX_DOCS_PER_USER == 99


def test_deleting_documents_frees_doc_numbers_for_new_uploads(module):
    """删掉资料后编号必须能回收，否则「累计上传过 99 份」等于永久报废。

    两条都要验：删掉的号被清掉；新资料能拿到腾出来的空号（分配取最小空闲号，
    不需要重排存活资料的编号 —— 重排会在并发任务之间改动对方正在用的编号）。
    """
    state = importlib.import_module("app.services.state")

    for index in range(99):
        state.upsert_document(USER_A, f"doc-{index}", f"资料 {index}", "INDEXED", 1)

    # Java 侧删掉了 10 份：建库请求里不再带它们，对账时回收编号。
    # before 取「全部登记完之后」，把这一批都算作旧资料（updated_at 是秒级精度）。
    remaining = [f"doc-{index}" for index in range(10, 99)]
    released = state.reconcile_documents(USER_A, remaining, before=int(time.time()) + 60)
    assert released == 10, released

    reused = state.upsert_document(USER_A, "doc-new", "新资料", "PARSING", 0)
    assert reused in range(1, 11), f"应当复用被腾出的空号，实际拿到 {reused}"

    # 再补到 99 份仍然成功，第 100 份才报上限 —— 边界必须是「同时 99」而不是「累计 99」。
    # 此时已有 89（留存）+ 1（doc-new）= 90 份，再补 9 份正好到 99。
    for index in range(9):
        state.upsert_document(USER_A, f"doc-fill-{index}", "补位", "INDEXED", 1)
    with pytest.raises(ValueError, match="上限"):
        state.upsert_document(USER_A, "doc-over", "越界", "PARSING", 0)


def test_reconcile_keeps_documents_registered_by_a_concurrent_task(module):
    """并发建库时，后一个任务刚登记的资料不能被前一个任务的对账删掉。

    实测踩过：任务 A 推进到 splitting 时按自己的资料集对账，把任务 B 刚登记的
    资料删了，B 随后报「资料 495 尚未登记编号」。对账只能删「早于本任务开始」的行。
    """
    state = importlib.import_module("app.services.state")

    # updated_at 是秒级精度，先写旧资料，再跨过一个秒边界取「任务开始时刻」，
    # 才能稳定区分「任务开始前就存在的」与「任务开始后才登记的」。
    state.upsert_document(USER_A, "doc-old", "旧资料", "INDEXED", 1)
    time.sleep(1.1)
    task_a_started = int(time.time())
    state.upsert_document(USER_A, "doc-live", "并发任务刚登记", "PARSING", 0)

    # 任务 A 的资料集只有 doc-a，但 doc-live 是任务 A 开始之后才登记的，必须留下。
    released = state.reconcile_documents(USER_A, ["doc-a"], before=task_a_started)
    assert released == 1, f"只应回收 doc-old，实际 {released}"
    assert state.document_number(USER_A, "doc-live") > 0, "并发任务的资料被误删"
    assert state.document_number(USER_A, "doc-old") == 0


def test_duplicate_chunk_id_in_one_batch_is_reported_by_doc(module, monkeypatch):
    """同批重复 chunk_id 要在写入前点名，而不是留给 Milvus 报 code=1100。"""
    ingest = importlib.import_module("app.services.ingest")

    class FakeEmbedder:
        degraded = False

        def embed(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class FakeStore:
        def delete_task(self, user_id, task_id):
            raise AssertionError("检测到重复主键时不该先删旧数据")

        def upsert(self, user_id, task_id, rows):
            raise AssertionError("检测到重复主键时不该调用 upsert")

    monkeypatch.setattr(ingest.runtime, "embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(ingest.runtime, "store", lambda: FakeStore())
    monkeypatch.setattr(ingest.runtime, "ensure_dim", lambda dim: None)

    rows = [
        {"chunk_id": "D99-C001", "doc_id": "doc-a", "excerpt": "甲"},
        {"chunk_id": "D99-C001", "doc_id": "doc-b", "excerpt": "乙"},
    ]
    with pytest.raises(ValueError) as excinfo:
        ingest._embed_and_store(USER_A, "task-dup", rows)
    message = str(excinfo.value)
    assert "重复 chunk_id" in message, message
    assert "doc-a" in message and "doc-b" in message, "报错要点名是哪两份资料撞的"
