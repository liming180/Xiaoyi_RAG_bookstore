"""J7 门禁（HTTP 侧）：两个真实账号之间的资料、任务、片段、会话、评测隔离。

为什么单独一个文件：`test_python_isolation.py` 用进程内 TestClient 直接验 Python 服务，
证明的是「AI 侧按 user_id 分桶」。但用户真正能碰到的边界在 Java 的公开接口上：
A 上传的资料，B 的列表里不能出现；A 的建库任务 id，B 拿来查必须 404；
B 拿 A 的资料 id 改/删/查片段/追问，都必须当作「不存在」。

前置条件（与 J1–J5 相同）：Java 8080 + Python 8000 已启动，两个 bootstrap 账号可用，
`MYSQL_DATABASE` 指向门禁库、`STORAGE_ROOT` 指向门禁盘。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


def _upload(client, name: str, text: str) -> dict:
    """上传一份 md，返回被接收的 DocumentVO。"""
    response = client.post(
        "/api/v1/documents",
        files=[("files", (name, text.encode("utf-8"), "text/markdown"))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    accepted = payload["data"]["accepted"]
    assert accepted, payload
    return accepted[0]


def test_documents_are_invisible_to_other_users(java_client, java_client_b, clean_db):
    """A 上传的资料不出现在 B 的列表里。"""
    doc = _upload(java_client, "a-private.md", "# A 的私有资料\n\n只有 A 能看见。\n")

    mine = java_client.get("/api/v1/documents").json()["data"]
    assert [row["id"] for row in mine] == [doc["id"]]

    theirs = java_client_b.get("/api/v1/documents").json()["data"]
    assert doc["id"] not in [row["id"] for row in theirs]
    assert theirs == [], "B 还没上传任何资料"


def test_same_content_from_two_users_creates_two_rows(java_client, java_client_b, clean_db):
    """同正文上传不能命中别人的去重记录，否则等于泄露「这份资料已存在」。"""
    body = "# 公共教材\n\n同一份正文。\n"
    mine = _upload(java_client, "same.md", body)
    theirs = _upload(java_client_b, "same.md", body)

    assert mine["id"] != theirs["id"], "跨用户去重必须互不影响"
    assert len(java_client.get("/api/v1/documents").json()["data"]) == 1
    assert len(java_client_b.get("/api/v1/documents").json()["data"]) == 1


def test_cross_user_update_and_delete_are_not_found(java_client, java_client_b, clean_db):
    """B 拿 A 的资料 id 改/删，一律 404/40401，而不是 403 或静默成功。"""
    doc = _upload(java_client, "guard.md", "# 受保护\n\n正文。\n")

    update = java_client_b.put(
        f"/api/v1/documents/{doc['id']}", json={"title": "被改了"}
    )
    assert update.status_code == 404, update.text
    assert update.json()["code"] == 40401

    delete = java_client_b.delete(f"/api/v1/documents/{doc['id']}")
    assert delete.status_code == 404, delete.text
    assert delete.json()["code"] == 40401

    still_there = java_client.get("/api/v1/documents").json()["data"]
    assert [row["id"] for row in still_there] == [doc["id"]]
    assert still_there[0]["title"] == "受保护"


def test_cross_user_task_and_chunks_are_not_found(java_client, java_client_b, clean_db):
    """建库任务是 A 的：B 查任务 404/40402，查片段只能看到自己的（空）。"""
    doc = _upload(java_client, "task.md", "# 任务资料\n\n正文。\n")
    rebuild = java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": 60, "overlap": 10}
    )
    assert rebuild.status_code == 200, rebuild.text
    task_id = rebuild.json()["data"]["id"]

    theirs = java_client_b.get(f"/api/v1/index/tasks/{task_id}")
    assert theirs.status_code == 404, theirs.text
    assert theirs.json()["code"] == 40402

    chunks = java_client_b.get("/api/v1/chunks", params={"docId": doc["id"]})
    assert chunks.status_code == 200, chunks.text
    assert chunks.json()["data"] == [], "B 不该看到 A 的片段"

    status = java_client_b.get("/api/v1/index/status").json()["data"]
    assert status["docCount"] == 0, status


def test_rebuild_and_delete_of_one_user_do_not_touch_the_other(
    java_client, java_client_b, clean_db
):
    """A 重建 + 删除资料，不影响 B 的资料与状态。"""
    mine = _upload(java_client, "a.md", "# A\n\nA 的正文。\n")
    theirs = _upload(java_client_b, "b.md", "# B\n\nB 的正文。\n")

    assert java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": 60, "overlap": 10}
    ).status_code == 200

    deleted = java_client.delete(f"/api/v1/documents/{mine['id']}")
    assert deleted.status_code == 200, deleted.text

    rows = java_client_b.get("/api/v1/documents").json()["data"]
    assert [row["id"] for row in rows] == [theirs["id"]], rows
    assert rows[0]["status"] == "UPLOADING", "B 的资料不该被 A 的操作改状态"


def test_conversations_and_messages_are_isolated(java_client, java_client_b, clean_db):
    """会话与消息按 owner 过滤：B 读不到 A 的会话，也读不到 A 的消息。

    契约里 `/conversations/{id}` 只有 DELETE，没有 GET，所以越权读取走消息列表端点：
    B 拿 A 的会话 id 取消息必须 404/40406。
    """
    created = java_client.post("/api/v1/conversations", json={"title": "A 的会话"})
    assert created.status_code == 200, created.text
    conversation_id = created.json()["data"]["id"]

    assert java_client_b.get("/api/v1/conversations").json()["data"] == []

    messages = java_client_b.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert messages.status_code == 404, messages.text
    assert messages.json()["code"] == 40406

    clear = java_client_b.delete(f"/api/v1/conversations/{conversation_id}/messages")
    assert clear.status_code == 404, clear.text
    assert clear.json()["code"] == 40406

    assert [row["id"] for row in java_client.get("/api/v1/conversations").json()["data"]] == [
        conversation_id
    ]


def test_eval_runs_and_feedback_are_isolated(java_client, java_client_b, clean_db):
    """评测批次列表与反馈汇总都只统计本人。"""
    started = java_client.post(
        "/api/v1/eval/batch", json={"mode": "both", "k": 1, "questionIds": ["T03"]}
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["data"]["id"]

    mine = java_client.get("/api/v1/eval/runs").json()["data"]
    assert [row["id"] for row in mine] == [run_id]

    theirs = java_client_b.get("/api/v1/eval/runs").json()["data"]
    assert theirs == [], "B 不该看到 A 的评测批次"

    peek = java_client_b.get(f"/api/v1/eval/runs/{run_id}")
    assert peek.status_code == 404, peek.text
    assert peek.json()["code"] == 40403

    summary = java_client_b.get("/api/v1/feedback/summary").json()["data"]
    assert summary["total"] == 0, summary
    assert summary["candidates"] == 0, summary
