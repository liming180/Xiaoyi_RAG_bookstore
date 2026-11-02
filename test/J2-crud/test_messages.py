"""J2 消息 CRUD：列表、F10 清空、limit/before 分页。

手册 §6「测试（test/J2-crud/ 下写）」第 2 条：
`test_messages.py`（造 3 条消息→查；F10 清空后消息 0 条但会话还在；分页 limit/before 生效）。

为什么直插库：J2 阶段没有写消息的接口 —— `POST /api/v1/chat/stream` 要等 J3 才实现，
所以用 pymysql 直接往 `message` 表插，这是手册认可的造数方式（`clean_db` 同理）。

契约对齐：

- `Message` required 12 项 `[id, conversationId, role, content, createdAt, citations, trace,
  usage, elapsedMs, degraded, suggestions, feedback]`，`additionalProperties: false`。
  注意 `trace`/`usage`/`feedback` 即使为空也必须出现（值为 null），不能省略 —— 这是
  `MessageVO` 类级不加 `@JsonInclude(NON_NULL)` 的原因。
- `role` 只能是 `user` / `assistant`。
- 消息按 `createdAt` 升序。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

MESSAGE_KEYS = {
    "id",
    "conversationId",
    "role",
    "content",
    "createdAt",
    "citations",
    "trace",
    "usage",
    "elapsedMs",
    "degraded",
    "suggestions",
    "feedback",
}


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


def _insert_messages(conversation_id: int, rows: list[tuple[str, str, int]]) -> None:
    """直插消息。rows 是 `(role, content, created_at)` 三元组。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO message (conversation_id, role, content, degraded, deleted, created_at)"
                " VALUES (%s, %s, %s, 0, 0, %s)",
                [(conversation_id, role, content, created_at) for role, content, created_at in rows],
            )
    finally:
        conn.close()


def _make_conversation(java_client) -> int:
    data = java_client.post("/api/v1/conversations", json={"title": "消息用例"}).json()["data"]
    return int(data["id"])


def test_list_messages_returns_contract_shape(java_client, clean_db):
    """造 3 条消息 → 查回来 3 条，字段集与契约一致，按 createdAt 升序。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)
    _insert_messages(
        conversation_id,
        [
            ("user", "读书会几点开始？", 1_700_000_000),
            ("assistant", "周六 14:00 至 16:00。", 1_700_000_001),
            ("user", "最多借几本？", 1_700_000_002),
        ],
    )

    resp = java_client.get(f"/api/v1/conversations/{conversation_id}/messages")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    rows = payload["data"]
    assert isinstance(rows, list), f"消息列表的 data 应是数组：{rows!r}"
    assert len(rows) == 3, rows
    for row in rows:
        assert set(row) == MESSAGE_KEYS, f"字段集不对：{sorted(row)}"
        assert row["role"] in ("user", "assistant")
        assert isinstance(row["citations"], list), "citations 必须是数组（空也要给 []）"
        assert row["suggestions"] == [], "J2 阶段 suggestions 恒为空数组"
    assert [row["content"] for row in rows] == [
        "读书会几点开始？",
        "周六 14:00 至 16:00。",
        "最多借几本？",
    ], "消息必须按 createdAt 升序"


def test_message_count_reflects_alive_messages(java_client, clean_db):
    """会话列表里的 messageCount 要跟真实消息条数对上。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)
    _insert_messages(
        conversation_id,
        [("user", "第一问", 1_700_000_010), ("assistant", "第一答", 1_700_000_011)],
    )

    rows = java_client.get("/api/v1/conversations").json()["data"]
    target = [row for row in rows if int(row["id"]) == conversation_id]

    assert len(target) == 1, rows
    assert target[0]["messageCount"] == 2, target[0]


def test_clear_messages_keeps_conversation(java_client, clean_db):
    """F10 清空：消息 0 条，但会话还在（这是与「删除会话」的关键区别）。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)
    _insert_messages(
        conversation_id,
        [
            ("user", "问题一", 1_700_000_100),
            ("assistant", "回答一", 1_700_000_101),
            ("user", "问题二", 1_700_000_102),
        ],
    )

    resp = java_client.delete(f"/api/v1/conversations/{conversation_id}/messages")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"] is None, "清空成功时 data 必须是 null"

    after = java_client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert after.status_code == 200, after.text
    assert after.json()["data"] == [], f"清空后不该还有消息：{after.json()['data']}"

    rows = java_client.get("/api/v1/conversations").json()["data"]
    still_there = [row for row in rows if int(row["id"]) == conversation_id]
    assert len(still_there) == 1, "清空消息不该把会话一起删掉"
    assert still_there[0]["messageCount"] == 0, still_there[0]

    # 库里是软删（deleted=1），不是物理删除。
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM message WHERE conversation_id = %s", (conversation_id,)
            )
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM message WHERE conversation_id = %s AND deleted = 0",
                (conversation_id,),
            )
            alive = cur.fetchone()[0]
    finally:
        conn.close()

    assert total == 3, f"软删不该物理删除消息，实际剩 {total} 行"
    assert alive == 0, f"清空后不该有未删消息，实际 {alive} 行"


def test_clear_messages_on_unknown_conversation_returns_40406(java_client, clean_db):
    """清空不存在的会话回 40406。"""
    resp = java_client.delete("/api/v1/conversations/999999/messages")

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 40406, resp.text


def test_messages_limit_takes_effect(java_client, clean_db):
    """limit 生效：要 2 条就只给 2 条，且是最早的两条（升序取前 N）。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)
    _insert_messages(
        conversation_id,
        [("user", f"第{i}问", 1_700_000_200 + i) for i in range(5)],
    )

    resp = java_client.get(f"/api/v1/conversations/{conversation_id}/messages", params={"limit": 2})

    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 2, rows
    assert [row["content"] for row in rows] == ["第0问", "第1问"], rows


def test_messages_before_cursor_takes_effect(java_client, clean_db):
    """before 生效：只返回 createdAt 严格小于游标的消息。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)
    _insert_messages(
        conversation_id,
        [("user", f"第{i}问", 1_700_000_300 + i) for i in range(4)],
    )

    resp = java_client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        params={"before": 1_700_000_302},
    )

    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert [row["content"] for row in rows] == ["第0问", "第1问"], rows


def test_messages_limit_out_of_range_returns_40001(java_client, clean_db):
    """limit 超过 200 是非法参数，回 40001（手册 §6 明写「分页参数非法要 400」）。"""
    if clean_db is None:
        pytest.skip("数据库不可用，无法造数")

    conversation_id = _make_conversation(java_client)

    resp = java_client.get(
        f"/api/v1/conversations/{conversation_id}/messages", params={"limit": 201}
    )

    assert resp.status_code == 400, resp.text
    payload = resp.json()
    assert payload["code"] == 40001, payload
    assert payload["data"] is None, payload
