"""J3 检索轨迹：`GET /api/v1/messages/{id}/trace` 与流里的 retrieval 一致。

手册 §7「测试（test/J3-sse/ 下写）」第 4 条：
`test_trace.py`（trace 行数与 retrieval 的 citations 条数一致）。

契约依据 `docs/api/openapi-public.yaml:319-348`：
- 无检索过程（direct 产出、或消息本身是用户提问）→ `data` 为 `null` 且 `code: 0`，**不报错**；
- 消息不存在 → 404 + 40407；
- `RetrievalTrace` required `[question, k, chunkSize, overlap, rows]`，`k` 1..10、`chunkSize` 50..1000；
- `TraceRow` required 12 项，`rank` ≥ 1、`retrieved` 是布尔。

为什么「行数 == 引用条数」是硬约束：`useChat` 拿到 done 的 messageId 后会立刻拉 trace 并渲染
「检索过程」抽屉（`frontend/src/features/chat/composables/useChat.ts:113`）。行数对不上，用户看到的
引用编号与检索明细就会错位。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse

pytestmark = pytest.mark.live

TRACE_KEYS = {"question", "k", "chunkSize", "overlap", "rows"}

ROW_KEYS = {
    "rank",
    "chunkId",
    "docId",
    "docTitle",
    "headingPath",
    "text",
    "start",
    "end",
    "score",
    "retrieved",
    "kind",
    "verified",
}


def _make_conversation(java_client) -> int:
    data = java_client.post("/api/v1/conversations", json={"title": "轨迹用例"}).json()["data"]
    return int(data["id"])


def _ask(java_client, conversation_id: int, question: str, mode: str = "rag", k: int = 3):
    """发一次流式问答，返回 `(done 帧, retrieval 帧的 citations, 全部事件名)`。"""
    status, content_type, events, text = read_sse(
        {
            "conversationId": str(conversation_id),
            "question": question,
            "mode": mode,
            "k": k,
        }
    )
    assert status == 200, f"SSE 应 200，实际 {status}：{text[:400]}"
    assert content_type.startswith("text/event-stream"), content_type

    done = None
    citations = []
    names = []
    for event in events:
        names.append(event.event)
        data = json.loads(event.data)
        if event.event == "retrieval":
            citations = data["citations"]
        elif event.event == "done":
            done = data
    assert done is not None, f"没有收到 done：{names}"
    return done, citations, names


def _get_trace(java_client, message_id) -> dict:
    resp = java_client.get(f"/api/v1/messages/{message_id}/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_trace_rows_match_retrieval_citations(java_client, clean_db):
    """trace 的 rows 条数必须等于流里 retrieval 的 citations 条数。"""
    conversation_id = _make_conversation(java_client)
    done, citations, _names = _ask(java_client, conversation_id, "普通图书最多借几本？", k=3)

    body = _get_trace(java_client, done["messageId"])

    assert body["code"] == 0, body
    trace = body["data"]
    assert trace is not None, f"rag 模式应有轨迹：{body}"
    assert set(trace) == TRACE_KEYS, f"轨迹字段集不对：{sorted(trace)}"
    assert len(trace["rows"]) == len(citations), (
        f"trace 行数 {len(trace['rows'])} 与 citations 条数 {len(citations)} 不一致"
    )


def test_trace_row_fields_match_contract(java_client, clean_db):
    """每一行都要满足 TraceRow 的 12 个 required 字段与取值约束。"""
    conversation_id = _make_conversation(java_client)
    done, citations, _names = _ask(java_client, conversation_id, "普通图书最多借几本？", k=3)

    trace = _get_trace(java_client, done["messageId"])["data"]

    for index, row in enumerate(trace["rows"], start=1):
        missing = ROW_KEYS - set(row)
        assert not missing, f"TraceRow 缺字段 {sorted(missing)}：{row}"
        assert row["rank"] == index, f"rank 应从 1 递增：{row['rank']}"
        assert row["retrieved"] is True, f"进入 top-k 的行 retrieved 应为 true：{row}"
        assert 0.0 <= row["score"] <= 1.0, f"score 越界：{row['score']}"
        assert isinstance(row["verified"], bool), row
        assert row["chunkId"] == citations[index - 1]["chunkId"], (
            f"第 {index} 行的 chunkId 与 retrieval 顺序不一致"
        )


def test_trace_echoes_question_and_params(java_client, clean_db):
    """轨迹要回显问题与建库参数，k 与请求一致、chunkSize/overlap 在契约区间内。"""
    conversation_id = _make_conversation(java_client)
    question = "读书会几点开始？"
    done, _citations, _names = _ask(java_client, conversation_id, question, k=2)

    trace = _get_trace(java_client, done["messageId"])["data"]

    assert trace["question"] == question, f"轨迹应回显原问题：{trace['question']!r}"
    assert trace["k"] == 2, f"k 应与请求一致：{trace['k']}"
    assert 50 <= trace["chunkSize"] <= 1000, f"chunkSize 越界：{trace['chunkSize']}"
    assert trace["overlap"] >= 0, f"overlap 不该为负：{trace['overlap']}"


def test_trace_is_null_for_direct_mode(java_client, clean_db):
    """direct 模式没有检索过程，trace 要回 code=0 + data=null（不报错）。"""
    conversation_id = _make_conversation(java_client)
    done, citations, names = _ask(java_client, conversation_id, "读书会几点开始？", mode="direct")

    assert not citations, f"direct 模式不该有 retrieval：{names}"
    body = _get_trace(java_client, done["messageId"])

    assert body["code"] == 0, f"无轨迹不是错误：{body}"
    assert body["data"] is None, f"direct 的 trace 应为 null：{body}"


def test_trace_is_null_for_user_message(java_client, clean_db):
    """用户消息没有检索过程，同样回 null 而不是 404。"""
    conversation_id = _make_conversation(java_client)
    _ask(java_client, conversation_id, "读书会几点开始？")

    messages = java_client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["data"]
    user_message = [item for item in messages if item["role"] == "user"][0]

    body = _get_trace(java_client, user_message["id"])

    assert body["code"] == 0, body
    assert body["data"] is None, f"用户消息的 trace 应为 null：{body}"


def test_trace_unknown_message_returns_40407(java_client, clean_db):
    """消息不存在 → 404 + 40407。"""
    resp = java_client.get("/api/v1/messages/999999/trace")

    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["code"] == 40407, body
    assert body["data"] is None, body


def test_trace_non_numeric_message_id_returns_40407(java_client, clean_db):
    """非数字 id 也要走 40407，不能让 NumberFormatException 变成 500。"""
    resp = java_client.get("/api/v1/messages/abc/trace")

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 40407, resp.text


def test_trace_of_deleted_message_returns_40407(java_client, clean_db):
    """清空会话后，原来的 messageId 应回 40407（软删后不再可见）。"""
    conversation_id = _make_conversation(java_client)
    done, _citations, _names = _ask(java_client, conversation_id, "读书会几点开始？")

    cleared = java_client.delete(f"/api/v1/conversations/{conversation_id}/messages")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["code"] == 0, cleared.text

    resp = java_client.get(f"/api/v1/messages/{done['messageId']}/trace")

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 40407, resp.text


def test_trace_k_one_has_single_row(java_client, clean_db):
    """k=1 时 trace 只有一行 —— 证明 k 一路传到了落库的轨迹里。"""
    conversation_id = _make_conversation(java_client)
    done, citations, _names = _ask(java_client, conversation_id, "普通图书最多借几本？", k=1)

    trace = _get_trace(java_client, done["messageId"])["data"]

    assert len(citations) == 1, citations
    assert len(trace["rows"]) == 1, trace
    assert trace["k"] == 1, trace
