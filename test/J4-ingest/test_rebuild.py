"""J4 门禁一：重建索引的参数校验与任务创建。

手册 §8「测试」第 1 条：`test_rebuild.py`（49/1001 越界 400、overlap>=chunkSize 400、合法 200 带 taskId）。

对齐的契约细节（docs/api/openapi-public.yaml）：

- `POST /api/v1/index/rebuild` 的 `x-error-codes: [40002, 40003, 40100, 40903, 50301]`。
  **40002 = chunkSize 越界、40003 = overlap 越界**，这是 docs/api/error-codes.md:79 明确拍板的编号
  （手册 §J4 曾把 40001/40002 分给这两个字段，与前端 mock 相反，以错误码表为准）。
- 已有任务在跑时再 POST 必须 409 + 40903（建库串行）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

TASK_KEYS = {
    "id",
    "status",
    "stage",
    "progress",
    "chunkSize",
    "overlap",
    "docCount",
    "chunkCount",
    "startedAt",
    "finishedAt",
}
STAGES = {"parsing", "splitting", "embedding", "summarizing", "done"}
STATUSES = {"PENDING", "RUNNING", "SUCCEEDED", "FAILED"}
MSG_CHUNK_SIZE = "片段长度需在 50-1000 之间"
MSG_OVERLAP = "重叠字数必须小于片段长度"


def _upload(java_client, name, text):
    """上传一份 md，返回 DocumentVO。"""
    files = [("files", (name, text.encode("utf-8"), "text/markdown"))]
    resp = java_client.post("/api/v1/documents", files=files)
    payload = resp.json()
    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, payload
    accepted = payload["data"]["accepted"]
    assert accepted, payload
    return accepted[0]


def _clear_running(clean_db):
    """清空建库相关状态（含 document 与磁盘文件），让每个用例从零资料开始。

    直接复用 `conftest.reset_ingest_state`：三个 J4 用例文件原先各自抄了一份只删
    `chunk` / `index_task` 的版本，导致 `document` 里的历史资料随用例数累积，
    单次建库要重新解析全部文件（J4 首轮 29 个用例跑了 70 分钟，且 15s 的
    `wait_until` 会超时）。
    """
    del clean_db  # 参数保留是为了不改调用点；真正的清理不依赖 fixture 实例
    from conftest import reset_ingest_state

    reset_ingest_state()


@pytest.mark.parametrize(
    "chunk_size,overlap,expected_code,expected_message",
    [
        (49, 10, 40002, MSG_CHUNK_SIZE),
        (1001, 10, 40002, MSG_CHUNK_SIZE),
        (50, 50, 40003, MSG_OVERLAP),
        (180, 180, 40003, MSG_OVERLAP),
        (180, 999, 40003, MSG_OVERLAP),
        (180, -1, 40003, MSG_OVERLAP),
    ],
)
def test_rebuild_rejects_invalid_params(
    java_client, clean_db, chunk_size, overlap, expected_code, expected_message
):
    """参数越界一律 400，且带中文 message（前端直接展示）。"""
    resp = java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": chunk_size, "overlap": overlap}
    )
    payload = resp.json()

    assert resp.status_code == 400, f"期望 400，实际 {resp.status_code}：{resp.text}"
    assert payload["code"] == expected_code, payload
    assert payload["message"] == expected_message, payload
    assert payload["data"] is None, "出错时 data 必须是 null（error-codes.md §2）"


def test_rebuild_accepts_boundary_chunk_size(java_client, clean_db):
    """50 与 1000 是闭区间端点，必须放行（越界判定写成开区间是常见错误）。"""
    _clear_running(clean_db)
    for size in (50, 1000):
        _clear_running(clean_db)
        resp = java_client.post(
            "/api/v1/index/rebuild", json={"chunkSize": size, "overlap": size - 1}
        )
        payload = resp.json()
        assert resp.status_code == 200, f"chunkSize={size} 应放行：{resp.text}"
        assert payload["code"] == 0, payload
        assert payload["data"]["chunkSize"] == size


def test_rebuild_returns_contract_shaped_task(java_client, clean_db):
    """合法请求返回任务对象，字段集与契约 IndexTask 完全一致。"""
    _clear_running(clean_db)
    _upload(java_client, "j4_rebuild.md", "# 借阅规则\n\n普通图书最多 4 本，借期 21 天。\n")

    resp = java_client.post("/api/v1/index/rebuild", json={"chunkSize": 180, "overlap": 30})
    payload = resp.json()

    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, payload
    task = payload["data"]
    assert set(task) == TASK_KEYS, f"字段集不对：{sorted(task)}"
    assert task["id"] is not None
    assert task["status"] in STATUSES, task
    assert task["stage"] in STAGES, task
    assert isinstance(task["progress"], int) and 0 <= task["progress"] <= 100, task
    assert task["chunkSize"] == 180
    assert task["overlap"] == 30
    assert isinstance(task["startedAt"], int) and task["startedAt"] > 0, task


def test_rebuild_while_running_returns_40903(java_client, clean_db):
    """建库串行：已有任务在跑时再 POST 必须 409 + 40903。"""
    _clear_running(clean_db)
    _upload(java_client, "j4_busy.md", "# 并发测试\n\n正文若干，用于占住任务队列。\n")

    first = java_client.post("/api/v1/index/rebuild", json={"chunkSize": 180, "overlap": 30})
    assert first.status_code == 200, first.text
    first_task = first.json()["data"]

    if first_task["status"] in ("SUCCEEDED", "FAILED"):
        pytest.skip("首个任务已瞬间结束，无法构造并发窗口")

    second = java_client.post("/api/v1/index/rebuild", json={"chunkSize": 200, "overlap": 40})
    payload = second.json()

    assert second.status_code == 409, f"期望 409，实际 {second.status_code}：{second.text}"
    assert payload["code"] == 40903, payload
    assert payload["data"] is None, payload


def test_rebuild_without_body_uses_defaults(java_client, clean_db):
    """缺 body 时用配置默认值（180/30），不报 40001。"""
    _clear_running(clean_db)
    _upload(java_client, "j4_default.md", "# 默认参数\n\n正文用于建库。\n")

    resp = java_client.post("/api/v1/index/rebuild")
    payload = resp.json()

    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, payload
    assert payload["data"]["chunkSize"] == 180, payload["data"]
    assert payload["data"]["overlap"] == 30, payload["data"]


def test_index_task_unknown_id_returns_40402(java_client):
    """不存在的任务 id → 404 + 40402，不能变 500。"""
    resp = java_client.get("/api/v1/index/tasks/999999")
    payload = resp.json()

    assert resp.status_code == 404, resp.text
    assert payload["code"] == 40402, payload
    assert payload["data"] is None, payload


def test_index_task_non_numeric_id_returns_40402(java_client):
    """非数字 id 同样走 40402（契约 EntityId 双形状，但不该泄漏 NumberFormatException）。"""
    resp = java_client.get("/api/v1/index/tasks/not-a-number")
    payload = resp.json()

    assert resp.status_code == 404, resp.text
    assert payload["code"] == 40402, payload
