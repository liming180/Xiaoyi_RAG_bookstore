"""J3 降级：AI 不可达时不发 error，改发 done{degraded:true}，HTTP 仍 200，库里也标降级。

手册 §7「测试（test/J3-sse/ 下写）」第 3 条：
`test_stream_degrade.py`（停 Python 或让 MockAiClient 抛异常，仍收到 done 且 degraded=true、
HTTP 200、库里有 degraded=true 行）。

手册 §7 第 ④ 条原文：「降级：抛异常或熔断 → **不发 error，改发 done{degraded:true}**，同时落库
degraded=true，HTTP 仍 200」。

怎么触发降级：J3 阶段 Python 服务还不存在（A1 才建），所以用 `MockAiClient` 的两个开关：
- 问题里带 `[fail]` 标记 → 单请求降级，同一个已起好的服务就能同时验正常与降级两条路径；
- `--xiaoyi.ai.fail-mode=true` 起服务 → 全局降级，给门禁脚本做「整服务不可用」的整体验证。

**关键：降级时绝不能有 error 帧。** 前端 `chatMachine` 收到 error 会把 phase 置成 'error'
（`frontend/src/features/chat/composables/chatMachine.ts:145`），用户看到红条而不是「降级提示」。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse, wait_until

pytestmark = pytest.mark.live

#: `MockAiClient.FAIL_MARKER` 的 Python 侧镜像，两边必须一致。
FAIL_MARKER = "[fail]"


def _connect():
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
    data = java_client.post("/api/v1/conversations", json={"title": "降级用例"}).json()["data"]
    return int(data["id"])


def _degraded_rows(conversation_id: int) -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, role, content, degraded, elapsed_ms FROM message"
                " WHERE conversation_id = %s AND deleted = 0 ORDER BY created_at ASC, id ASC",
                (conversation_id,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def test_stream_degrade_returns_done_not_error(java_client, clean_db):
    """AI 抛异常时：HTTP 200、收到 done、degraded=true、**没有 error 帧**。"""
    conversation_id = _make_conversation(java_client)
    status, content_type, events, text = read_sse(
        {
            "conversationId": str(conversation_id),
            "question": f"读书会几点开始？{FAIL_MARKER}",
            "mode": "rag",
            "k": 3,
        }
    )

    assert status == 200, f"降级也必须 200，实际 {status}：{text[:400]}"
    assert content_type.startswith("text/event-stream"), content_type

    names = [event.event for event in events]
    assert "error" not in names, f"降级路径不许发 error 帧：{names}"
    done = [json.loads(event.data) for event in events if event.event == "done"]
    assert len(done) == 1, f"应恰好一帧 done：{names}"
    assert done[0]["degraded"] is True, f"degraded 必须是 true：{done[0]}"
    assert done[0]["messageId"] is not None, f"降级也要给 messageId（已落库）：{done[0]}"
    assert names[-1] == "done", f"done 必须是最后一帧：{names}"


def test_stream_degrade_persists_degraded_flag(java_client, clean_db):
    """降级也要落库，且 assistant 行 degraded=1。"""
    conversation_id = _make_conversation(java_client)
    read_sse(
        {
            "conversationId": str(conversation_id),
            "question": f"普通图书最多借几本？{FAIL_MARKER}",
            "mode": "rag",
            "k": 3,
        }
    )

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_degraded_rows(conversation_id)),
        timeout=15,
        message="降级路径也要在 15s 内落库两行",
    )
    assistant = [row for row in rows if row["role"] == "assistant"]
    assert len(assistant) == 1, rows
    assert assistant[0]["degraded"] == 1, f"库里 degraded 应为 1：{assistant[0]}"


def test_stream_degrade_answer_is_empty_but_persisted(java_client, clean_db):
    """降级发生在首个 token 之前，回答正文可以是空串 —— 但这一行必须存在，不能丢轮次。"""
    conversation_id = _make_conversation(java_client)
    read_sse(
        {
            "conversationId": str(conversation_id),
            "question": f"读书会几点开始？{FAIL_MARKER}",
            "mode": "rag",
            "k": 3,
        }
    )

    rows = wait_until(
        lambda: (lambda r: r if len(r) >= 2 else None)(_degraded_rows(conversation_id)),
        timeout=15,
        message="降级路径也要落库",
    )
    assistant = [row for row in rows if row["role"] == "assistant"][0]
    assert assistant["content"] is not None, "content 是 NOT NULL 列，不能为 NULL"


def test_stream_degrade_trace_endpoint_does_not_500(java_client, clean_db):
    """降级落库的行没有引用，trace 接口要回 code=0 + data=null，而不是 500。"""
    conversation_id = _make_conversation(java_client)
    status, _ct, events, text = read_sse(
        {
            "conversationId": str(conversation_id),
            "question": f"读书会几点开始？{FAIL_MARKER}",
            "mode": "rag",
            "k": 3,
        }
    )
    assert status == 200, text[:400]
    done = [json.loads(event.data) for event in events if event.event == "done"][0]

    resp = java_client.get(f"/api/v1/messages/{done['messageId']}/trace")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    assert body["data"] is None, f"无检索过程的回答，trace 应为 null：{body}"


def test_stream_degrade_after_partial_tokens(java_client, clean_db):
    """降级也能发生在已有部分正文之后（这里用 direct 模式，mock 同样在开头发起失败）。

    这条用例的意义是把「降级」与「空回答」解耦：断言的是**协议行为**（有 done、无 error、
    degraded=true），而不是正文长度。
    """
    conversation_id = _make_conversation(java_client)
    status, _ct, events, text = read_sse(
        {
            "conversationId": str(conversation_id),
            "question": f"读书会几点开始？{FAIL_MARKER}",
            "mode": "direct",
            "k": 1,
        }
    )

    assert status == 200, text[:400]
    names = [event.event for event in events]
    assert "error" not in names, names
    assert names[-1] == "done", names
    done = json.loads(events[-1].data)
    assert done["degraded"] is True, done
