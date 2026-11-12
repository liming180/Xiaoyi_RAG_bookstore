"""N3：全局摘要卡必须真生成、能过滤、能兜底，且失败不拖垮建库。

修之前（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §5.1）：
`ingest.py` 的 `summarizing` 阶段只有 `_pause()`，没有任何生成逻辑；
`splitter.py` 恒写 `"kind": "chunk"`。契约侧（`ChunkKind=summary|rule`、
`RetrieveRequest.kind`、`chunk` 表的 `kind`/`verified` 列、前端徽标）全部就绪，
缺的只是「真的生成」。

本文件守六件事（对应提示词 §5.3 的六条用例）：

1. 建库后 `kind=summary` 非空，且 `chunk_id` 是 `D00-C001` 这一族；
2. 规则卡正文含真实条款里的数字（「4 本」「21 天」）；
3. 摘要卡按用户隔离，A 的卡不出现在 B 的列表与检索里；
4. `gen_summary=false` 时一张卡都没有，任务仍 SUCCEEDED，manifest.summary 为 null；
5. 问「整个资料库」这类全局问题时，引用里至少有一条摘要卡（兜底生效）；
6. 摘要生成失败（provider 抛异常）时任务仍 SUCCEEDED。

**第 6 条在这里用「provider 没有 complete_sync」模拟**：真去造一个会抛异常的
provider 需要替换 runtime 内部对象，而那正是被测代码。用「没有同步补全能力」
这条真实存在的分支更干净 —— 它同样是「生成不出来」，且不会因为测试技巧而失真。
"""

from __future__ import annotations

import json

import pytest

from ai_app_loader import load_app

TOKEN = "n3-summary-token"
USER = 61
OTHER_USER = 62

CORPUS = [
    (
        "01_活动说明.md",
        "book-01",
        "# 星河读书会活动说明\n\n读书会每周六 14:00 至 16:00 在社区文化中心二层举行。\n",
    ),
    (
        "02_借阅规则.md",
        "book-02",
        "# 星河读书会借阅规则\n\n已登记成员每人最多同时借阅 4 本普通图书，每本借期 21 天。\n"
        "普通图书在到期前可申请续借 1 次，续借增加 7 天。\n",
    ),
    (
        "03_空间预约.md",
        "book-03",
        "# 讨论空间预约\n\n讨论空间供 3 至 6 人的阅读小组使用，可以提前 2 天预约，每次最长 2 小时。\n",
    ),
]


@pytest.fixture()
def module(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    return load_app(monkeypatch, TOKEN)


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


def _headers(user: int = USER) -> dict[str, str]:
    return {"X-Internal-Token": TOKEN, "X-User-Id": str(user)}


def _build(
    client,
    user: int = USER,
    gen_summary: bool = True,
    key: str = "sk-n3",
    documents: list[tuple[str, str, str]] | None = None,
) -> str:
    """建一次库并等终态，返回 task_id。

    @param documents `(文件名, doc_id, 正文)` 三元组；省略则用本模块的 CORPUS
    """
    corpus = documents if documents is not None else CORPUS
    response = client.post(
        "/internal/v1/documents/parse",
        headers=_headers(user),
        json={
            "documents": [
                {"doc_id": doc_id, "name": name, "title": name, "text": text}
                for name, doc_id, text in corpus
            ],
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": key,
            "generation": "g-1",
            "gen_summary": gen_summary,
        },
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["task_id"]
    task = client.get(f"/internal/v1/ingest/{task_id}", headers=_headers(user)).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def _task(client, task_id: str, user: int = USER) -> dict:
    return client.get(f"/internal/v1/ingest/{task_id}", headers=_headers(user)).json()["data"]


def _cards(task: dict, kind: str | None = None) -> list[dict]:
    return [
        chunk
        for chunk in task["chunks"]
        if chunk["kind"] in ("summary", "rule") and (kind is None or chunk["kind"] == kind)
    ]


def _retrieve(client, question: str, user: int = USER, k: int = 3) -> dict:
    response = client.post(
        "/internal/v1/retrieve",
        headers=_headers(user),
        json={"question": question, "k": k},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_summary_cards_generated(client) -> None:
    """建库后必须有两张卡：统计卡 + 规则卡，编号 D00-C001 / D00-C002。"""
    task = _task(client, _build(client))
    cards = _cards(task)

    assert cards, f"没有生成摘要卡：{[c['kind'] for c in task['chunks']]}"
    assert {card["kind"] for card in cards} == {"summary", "rule"}, cards
    for card in cards:
        # 契约 pattern 是 ^D\d{2}-C\d{3}$；摘要卡固定用文档号 00。
        assert card["chunk_id"].startswith("D00-C"), card["chunk_id"]
        assert card["doc_id"] == "__summary__", card
        assert card["doc_title"] == "全库摘要", card
        assert card["verified"] is True, card
        assert card["text"].strip(), card


def test_summary_card_counts_documents(client) -> None:
    """统计卡的正文要能回答「一共几份资料」—— 这是它存在的理由。"""
    task = _task(client, _build(client))
    summary = _cards(task, "summary")[0]

    assert f"{len(CORPUS)} 份资料" in summary["text"], summary["text"]


def test_rule_card_contains_borrow_rule(client) -> None:
    """规则卡正文必须含真实条款里的数字（4 本 / 21 天），而不是随便抽一句。"""
    task = _task(client, _build(client))
    rule = _cards(task, "rule")[0]

    assert "4" in rule["text"] and "21" in rule["text"], rule["text"]


def test_summary_cards_are_user_scoped(client) -> None:
    """A 的摘要卡不出现在 B 的建库结果与检索结果里。

    两个用户刻意给**不同语料**：语料相同的话两边的卡片正文天然一样，
    「隔离没做好」和「隔离做对了」看起来完全一致，这条断言就白测了。
    """
    owner_task = _build(client, USER, key="sk-owner")
    other_docs = [
        (
            "09_仅B可见.md",
            "book-09",
            "# 仅 B 可见的规则\n\nB 的私人规则：每月最多预约 9 次，每次 9 小时。\n",
        )
    ]
    other_task = _build(client, OTHER_USER, key="sk-other", documents=other_docs)

    owner_cards = _cards(_task(client, owner_task, USER))
    other_cards = _cards(_task(client, other_task, OTHER_USER))
    assert owner_cards and other_cards
    assert owner_cards[0]["text"] != other_cards[0]["text"], (
        "两个用户的摘要卡正文相同，说明隔离没生效（或者测试给了相同语料）"
    )
    assert "9" in other_cards[1]["text"] or "9" in other_cards[0]["text"], other_cards

    # B 检索时只看得到自己的语料。
    result = _retrieve(client, "整个资料库一共多少份资料？", OTHER_USER)
    assert result["citations"], result
    for citation in result["citations"]:
        assert citation["doc_id"] in ("__summary__", "book-09"), citation


def test_gen_summary_false_skips_cards(client) -> None:
    """`gen_summary=false` 时一张卡都没有，但任务仍 SUCCEEDED。

    这条守的是「摘要卡是增强，不是建库的前提」—— 关掉它建库必须照常成功。
    """
    task_id = _build(client, USER, gen_summary=False, key="sk-nosum")
    task = _task(client, task_id)

    assert task["status"] == "SUCCEEDED", task
    assert _cards(task) == [], f"关掉开关后不该有卡片：{_cards(task)}"
    assert task["chunk_count"] == len(task["chunks"]), task

    manifest = client.get("/internal/v1/index/status", headers=_headers(USER)).json()["data"]
    assert manifest["summary"] is None, manifest


def test_manifest_reports_summary_cards(client) -> None:
    """manifest.summary 如实反映卡片数量与类型，供 Java 与排障判断。"""
    _build(client, USER, gen_summary=True, key="sk-manifest")
    manifest = client.get("/internal/v1/index/status", headers=_headers(USER)).json()["data"]

    assert manifest["summary"] is not None, manifest
    assert manifest["summary"]["cards"] == 2, manifest
    assert set(manifest["summary"]["kinds"]) == {"summary", "rule"}, manifest


def test_summary_fallback_when_global_question(client) -> None:
    """问「整个资料库」时，引用里至少有一条摘要卡（兜底生效）。"""
    _build(client, USER, key="sk-fallback")

    result = _retrieve(client, "整个资料库一共多少份资料？都涵盖了什么？")
    kinds = [citation["kind"] for citation in result["citations"]]

    assert any(kind in ("summary", "rule") for kind in kinds), (
        f"全局问题没有命中摘要卡：{[(c['chunk_id'], c['kind']) for c in result['citations']]}"
    )
    # k 必须保持不变：替换而不是追加。
    assert len(result["citations"]) == 3, result["citations"]
    assert len(result["rows"]) == len(result["citations"]), "轨迹行必须与引用一一对应"


def test_normal_question_does_not_get_summary_card(client) -> None:
    """普通问题**不该**被塞摘要卡。

    这条反向用例是本文件里最重要的一条：提示词字面写的是「前 k 没有卡片就替换末位」，
    照字面实现会让每个问题都拿到一张「全库共 3 份资料」。实测 A3 五条用例同时失败。
    """
    _build(client, USER, key="sk-normal")

    result = _retrieve(client, "普通图书最多借几本？")
    kinds = [citation["kind"] for citation in result["citations"]]

    assert kinds and all(kind == "chunk" for kind in kinds), (
        f"普通问答被塞了摘要卡：{[(c['chunk_id'], c['kind']) for c in result['citations']]}"
    )


def test_kind_filter_returns_only_cards(client) -> None:
    """`kind=summary` 只回统计卡，`kind=rule` 只回规则卡。"""
    _build(client, USER, key="sk-kind")

    summaries = client.post(
        "/internal/v1/retrieve",
        headers=_headers(USER),
        json={"question": "整个资料库一共多少份资料？", "k": 3, "kind": "summary"},
    ).json()["data"]
    assert summaries["citations"], summaries
    assert all(c["kind"] == "summary" for c in summaries["citations"]), summaries

    rules = client.post(
        "/internal/v1/retrieve",
        headers=_headers(USER),
        json={"question": "谁有资格借书？", "k": 3, "kind": "rule"},
    ).json()["data"]
    assert rules["citations"], rules
    assert all(c["kind"] == "rule" for c in rules["citations"]), rules


def test_summary_generation_failure_does_not_fail_task(client, monkeypatch) -> None:
    """摘要生成失败时任务仍 SUCCEEDED，只是没有卡片。

    做法：让 `summarizer.generate` 整段抛异常。`_summarize` 会吞掉它并返回空列表，
    这正是「摘要失败不能让建库失败」那条约束的落点。
    """
    from app.core.rag import summarizer
    from app.services import ingest

    def explode(*args, **kwargs):
        raise RuntimeError("模拟 LLM 超时")

    monkeypatch.setattr(ingest.summarizer, "generate", explode)
    # 顺带确认模块是同一个对象：不是在测两份代码。
    assert ingest.summarizer is summarizer

    task_id = _build(client, USER, key="sk-fail")
    task = _task(client, task_id)
    assert task["status"] == "SUCCEEDED", task
    assert _cards(task) == [], f"生成失败时不该有卡片：{_cards(task)}"

    manifest = client.get("/internal/v1/index/status", headers=_headers(USER)).json()["data"]
    assert manifest["summary"] is None, manifest


def test_summary_cards_excluded_from_doc_count(client) -> None:
    """摘要卡的 doc_id 是 `__summary__`，不能算进 doc_count。"""
    _build(client, USER, key="sk-doccount")
    manifest = client.get("/internal/v1/index/status", headers=_headers(USER)).json()["data"]

    assert manifest["doc_count"] == len(CORPUS), manifest
