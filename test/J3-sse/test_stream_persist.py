"""J3 落库：done 之后 message 表里必须有一问一答两行，且字段齐全。

手册 §7「测试（test/J3-sse/ 下写）」第 2 条：
`test_stream_persist.py`（done 后查 message 表，assistant 行存在、citations_json 非空、
elapsed_ms>0、degraded=false）。

为什么必须先收完 done 再查库：done 帧是在落库任务**之后**才发的（`ChatServiceImpl.persistAndFinish`
里 `persistTurn` → `emitDone`），所以「收到 done」等价于「落库已完成」。这条时序是前端能立刻拉
trace 的前提（`frontend/src/features/chat/composables/useChat.ts:113`）。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse, wait_until

pytestmark = pytest.mark.live


def _connect():
    """开一条测试库连接；驱动缺失时让用例 skip 而不是 fail。"""
    pymysql = pytest.importorskip("pymysql", reason="需要 pymysql 直连测试库")
    from conftest import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

    return pymysql.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True,
    )


def _make_conversation(java_client) -> int:
    data = java_client.post("/api/v1/conversations", json={"title": "落库用例"}).json()["data"]
    return int(data["id"])


def _ask(java_client, conversation_id: int, question: str, mode: str = "rag", k: int = 3):
    """发一次流式问答，返回 `(done 帧 data, 全部事件名)`。"""
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
    names = []
    for event in events:
        names.append(event.event)
        if event.event == "done":
            done = json.loads(event.data)
    assert done is not None, f"没有收到 done：{names}"
    return done, names


def _fetch_rows(conversation_id: int) -> list[dict]:
    """读该会话的全部未删除消息，按 created_at 升序。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, role, content, mode, top_k, citations_json, retrieval_trace_json,"
                " usage_json, elapsed_ms, degraded FROM message"
                " WHERE conversation_id = %s AND deleted = 0"
                " ORDER BY created_at ASC, id ASC",
                (conversation_id,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def test_stream_persists_user_and_assistant_rows(java_client, clean_db):
    """一问一答落成两行：user 行是原问题，assistant 行是拼接后的完整回答。"""
    conversation_id = _make_conversation(java_client)
    done, _names = _ask(java_client, conversation_id, "普通图书最多借几本？")

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_fetch_rows(conversation_id)),
        timeout=15,
        message="done 之后 15s 内应落库两行消息",
    )

    assert len(rows) == 2, f"应恰好两行，实际 {len(rows)}：{rows}"
    user_row, assistant_row = rows
    assert user_row["role"] == "user", user_row
    assert user_row["content"] == "普通图书最多借几本？", user_row
    assert user_row["degraded"] == 0, "用户消息不该被标降级"
    assert assistant_row["role"] == "assistant", assistant_row
    assert assistant_row["content"], "助手回答不能为空"
    assert assistant_row["mode"] == "rag", assistant_row
    assert assistant_row["top_k"] == 3, assistant_row


def test_stream_done_message_id_points_to_assistant_row(java_client, clean_db):
    """done.messageId 必须是**数据库真实 id**，否则前端拿它拉 trace 会 404。"""
    conversation_id = _make_conversation(java_client)
    done, _names = _ask(java_client, conversation_id, "读书会几点开始？")

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_fetch_rows(conversation_id)),
        timeout=15,
        message="done 之后应落库两行",
    )
    assistant_row = [row for row in rows if row["role"] == "assistant"][0]

    assert str(done["messageId"]) == str(assistant_row["id"]), (
        f"done.messageId={done['messageId']!r} 与库里 assistant id={assistant_row['id']!r} 不一致"
    )


def test_stream_persists_citations_and_trace(java_client, clean_db):
    """assistant 行的 citations_json 与 retrieval_trace_json 都要有内容且能解析。"""
    conversation_id = _make_conversation(java_client)
    _ask(java_client, conversation_id, "普通图书最多借几本？", k=3)

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_fetch_rows(conversation_id)),
        timeout=15,
        message="done 之后应落库两行",
    )
    assistant_row = [row for row in rows if row["role"] == "assistant"][0]

    citations_raw = assistant_row["citations_json"]
    assert citations_raw, f"citations_json 不该为空：{citations_raw!r}"
    citations = json.loads(citations_raw)
    assert isinstance(citations, list) and len(citations) == 3, citations

    trace_raw = assistant_row["retrieval_trace_json"]
    assert trace_raw, f"retrieval_trace_json 不该为空：{trace_raw!r}"
    trace = json.loads(trace_raw)
    assert isinstance(trace, dict), trace
    assert trace["k"] == 3, trace
    assert len(trace["rows"]) == len(citations), (
        f"trace 行数 {len(trace['rows'])} 应与引用条数 {len(citations)} 一致"
    )
    for index, row in enumerate(trace["rows"], start=1):
        assert row["rank"] == index, f"rank 应从 1 递增：{trace['rows']}"
        assert row["retrieved"] is True, row


def test_stream_persists_elapsed_and_degraded(java_client, clean_db):
    """正常路径：elapsed_ms > 0 且 degraded = 0。"""
    conversation_id = _make_conversation(java_client)
    _ask(java_client, conversation_id, "读书会几点开始？")

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_fetch_rows(conversation_id)),
        timeout=15,
        message="done 之后应落库两行",
    )
    assistant_row = [row for row in rows if row["role"] == "assistant"][0]

    assert assistant_row["elapsed_ms"] > 0, f"elapsed_ms 应大于 0：{assistant_row}"
    assert assistant_row["degraded"] == 0, f"正常路径 degraded 应为 0：{assistant_row}"
    assert assistant_row["usage_json"], f"usage_json 不该为空：{assistant_row}"


def test_stream_second_turn_sees_history(java_client, clean_db):
    """同一会话第二问要带上一轮历史（Java 侧截断后透传），两问共落四行。"""
    conversation_id = _make_conversation(java_client)
    _ask(java_client, conversation_id, "读书会几点开始？")
    _ask(java_client, conversation_id, "那借书呢？")

    rows = wait_until(
        lambda: (lambda r: r if len(r) == 4 else None)(_fetch_rows(conversation_id)),
        timeout=15,
        message="两轮问答应落四行",
    )
    roles = [row["role"] for row in rows]
    assert roles == ["user", "assistant", "user", "assistant"], roles
    assert rows[2]["content"] == "那借书呢？", rows[2]


def test_stream_marks_conversation_updated(java_client, clean_db):
    """问答后会话的 updatedAt 要前进，且 messageCount 变成 2（列表页靠这两个字段排序/显示）。"""
    conversation_id = _make_conversation(java_client)
    before = java_client.get("/api/v1/conversations").json()["data"]
    before_row = [item for item in before if str(item["id"]) == str(conversation_id)][0]
    assert before_row["messageCount"] == 0, before_row

    _ask(java_client, conversation_id, "读书会几点开始？")

    after = wait_until(
        lambda: next(
            (
                item
                for item in java_client.get("/api/v1/conversations").json()["data"]
                if str(item["id"]) == str(conversation_id) and item["messageCount"] == 2
            ),
            None,
        ),
        timeout=15,
        message="问答后会话 messageCount 应变成 2",
    )
    assert after["updatedAt"] >= before_row["updatedAt"], (before_row, after)
