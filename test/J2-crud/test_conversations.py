"""J2 会话 CRUD：建 → 查 → 删，以及软删语义。

手册 §6「测试（test/J2-crud/ 下写）」第 1 条：
`test_conversations.py`（建→查→删；删后列表不含；软删语义正确）。

契约对齐（docs/api/openapi-public.yaml）：

- `Conversation` required `[id, title, createdAt, updatedAt, messageCount]`，`additionalProperties: false`
  —— 字段多一个少一个都算违约，所以这里逐字段断言键集。
- 列表端点是双形状（裸数组 或 `{items: [...]}`），后端默认回裸数组；
  用例两种都接受，与 `frontend/src/api/modules/chat.ts` 的消费方式一致。
- 会话不存在回 `40406`（不是 40401），见 `docs/api/error-codes.md`。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

CONVERSATION_KEYS = {"id", "title", "createdAt", "updatedAt", "messageCount"}


def _items(payload):
    """列表端点双形状归一：裸数组或 {items: [...]}。"""
    data = payload["data"]
    if isinstance(data, dict):
        assert "items" in data, f"对象形状的列表必须带 items：{data!r}"
        return data["items"]
    assert isinstance(data, list), f"列表端点的 data 只能是数组或 {{items}}：{data!r}"
    return data


def test_create_conversation_returns_contract_shape(java_client, clean_db):
    """新建会话：回完整 Conversation，title 生效，messageCount 从 0 起。"""
    resp = java_client.post("/api/v1/conversations", json={"title": "读书会相关问题"})

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    data = payload["data"]
    assert set(data) == CONVERSATION_KEYS, f"字段集不对：{sorted(data)}"
    assert data["title"] == "读书会相关问题"
    assert data["messageCount"] == 0
    assert isinstance(data["id"], str) and data["id"]
    assert data["createdAt"] > 0 and data["updatedAt"] >= data["createdAt"]


def test_create_conversation_without_title_falls_back_to_default(java_client, clean_db):
    """body 缺省（或 title 为空）时回落「新会话」，不报 40001。"""
    resp = java_client.post("/api/v1/conversations", json={})

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["title"] == "新会话", payload["data"]


def test_list_conversations_is_newest_first(java_client, clean_db):
    """列表按 updatedAt 倒序：后建的必须排前面。"""
    first = java_client.post("/api/v1/conversations", json={"title": "第一个"}).json()["data"]
    second = java_client.post("/api/v1/conversations", json={"title": "第二个"}).json()["data"]

    resp = java_client.get("/api/v1/conversations")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    ids = [row["id"] for row in _items(payload)]
    assert ids.index(second["id"]) < ids.index(first["id"]), f"排序不对：{ids}"
    for row in _items(payload):
        assert set(row) == CONVERSATION_KEYS, f"字段集不对：{sorted(row)}"


def test_delete_conversation_removes_it_from_list(java_client, clean_db):
    """删掉的会话不再出现在列表里。"""
    created = java_client.post("/api/v1/conversations", json={"title": "待删除"}).json()["data"]

    resp = java_client.delete(f"/api/v1/conversations/{created['id']}")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["code"] == 0, payload
    assert payload["data"] is None, "删除成功时 data 必须是 null"

    remaining = [row["id"] for row in _items(java_client.get("/api/v1/conversations").json())]
    assert created["id"] not in remaining, f"删除后仍在列表里：{remaining}"


def test_deleted_conversation_is_soft_deleted(java_client, clean_db):
    """软删语义：库里那行还在，只是 deleted=1；接口层当它不存在（40406）。

    这是「软删」与「物理删除」的分水岭 —— 如果实现改成 DELETE FROM，
    这条会直接失败，提醒实现者别动历史数据。
    """
    pymysql = pytest.importorskip("pymysql", reason="需要 pymysql 直查库")
    if clean_db is None:
        pytest.skip("数据库不可用，跳过软删语义校验")

    created = java_client.post("/api/v1/conversations", json={"title": "软删验证"}).json()["data"]
    java_client.delete(f"/api/v1/conversations/{created['id']}")

    from conftest import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

    conn = pymysql.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT deleted FROM conversation WHERE id = %s", (int(created["id"]),)
            )
            row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None, "软删不该把行物理删掉"
    assert row[0] == 1, f"deleted 应为 1，实际 {row[0]}"

    resp = java_client.get(f"/api/v1/conversations/{created['id']}/messages")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == 40406, resp.text


def test_delete_unknown_conversation_returns_40406(java_client, clean_db):
    """删不存在的会话回 40406，而不是 500 或静默成功。"""
    resp = java_client.delete("/api/v1/conversations/999999")

    assert resp.status_code == 404, resp.text
    payload = resp.json()
    assert payload["code"] == 40406, payload
    assert payload["data"] is None, payload
