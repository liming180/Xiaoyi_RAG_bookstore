"""J4 门禁二：建库任务的轮询推进。

手册 §8「测试」第 2 条：`test_task_polling.py`（wait_until progress==100 且 status=SUCCEEDED、
stage 走完五值、docCount/chunkCount 与文档数片段数一致）。

这里额外守两条契约细节：

- `stage` 必须是契约白名单五值之一（`parsing/splitting/embedding/summarizing/done`）。
  手册 §J4 明令「不许把 Python 原始 stage 直出」，所以哪怕 Python 回 `embedding_done` 这种值，
  Java 也必须映射进白名单。
- 终态 `progress` 恒 100 且 `finishedAt` 非空（契约 IndexTask.description 原文）。
"""

from __future__ import annotations

import pytest

from conftest import wait_until

pytestmark = pytest.mark.live

STAGES = ["parsing", "splitting", "embedding", "summarizing", "done"]
STAGE_SET = set(STAGES)
TERMINAL = {"SUCCEEDED", "FAILED"}


def _clear_running(clean_db):
    """清空建库相关状态（含 document 与磁盘文件），让每个用例从零资料开始。

    复用 `conftest.reset_ingest_state`，理由见该函数 docstring：只删 chunk/index_task
    会让 document 里的历史资料累积，单次建库被迫重新解析全部文件。
    """
    del clean_db  # 参数保留是为了不改调用点
    from conftest import reset_ingest_state

    reset_ingest_state()


def _upload(java_client, name, text):
    files = [("files", (name, text.encode("utf-8"), "text/markdown"))]
    resp = java_client.post("/api/v1/documents", files=files)
    payload = resp.json()
    assert resp.status_code == 200, resp.text
    accepted = payload["data"]["accepted"]
    assert accepted, payload
    return accepted[0]


def _start_rebuild(java_client, clean_db, chunk_size=180, overlap=30):
    """清库 → 传一份资料 → 触发重建，返回 (task, doc)。"""
    _clear_running(clean_db)
    doc = _upload(
        java_client,
        "j4_polling.md",
        "# 轮询测试\n\n"
        "普通图书每人最多同时借阅 4 本，每本借期 21 天。\n\n"
        "续借一次增加 7 天，逾期不可续借。\n\n"
        "讨论空间需要 3 至 6 人，每次最长 2 小时。\n\n"
        "预约的空间不能使用时应至少提前 30 分钟取消。\n",
    )
    resp = java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": chunk_size, "overlap": overlap}
    )
    payload = resp.json()
    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, payload
    return payload["data"], doc


def _poll_until_terminal(java_client, task_id, timeout=15.0):
    """轮询到终态，返回 (最终任务, 观察到的所有 (status, stage, progress) 序列)。"""
    seen: list[tuple[str, str, int]] = []

    def _fetch():
        resp = java_client.get(f"/api/v1/index/tasks/{task_id}")
        payload = resp.json()
        assert resp.status_code == 200, resp.text
        task = payload["data"]
        seen.append((task["status"], task["stage"], task["progress"]))
        return task if task["status"] in TERMINAL else None

    final = wait_until(_fetch, timeout=timeout, message=f"建库任务 {task_id} 未在 {timeout}s 内到终态")
    return final, seen


def test_task_reaches_succeeded_with_progress_100(java_client, clean_db):
    """任务必须推进到 SUCCEEDED 且 progress=100，并写 finishedAt。"""
    task, _doc = _start_rebuild(java_client, clean_db)
    final, _seen = _poll_until_terminal(java_client, task["id"])

    assert final["status"] == "SUCCEEDED", final
    assert final["progress"] == 100, final
    assert final["stage"] == "done", final
    assert isinstance(final["finishedAt"], int) and final["finishedAt"] > 0, final
    assert final["finishedAt"] >= final["startedAt"], final


def test_task_stage_visits_all_five_values(java_client, clean_db):
    """stage 必须走完契约五值（parsing → splitting → embedding → summarizing → done）。

    允许同一 stage 被观察到多次（轮询周期比 mock 推进快），但**不能跳**：
    跳值意味着 Java 把 Python 的原始 stage 直出了，或者轮询节拍与阶段窗口不对齐。
    """
    task, _doc = _start_rebuild(java_client, clean_db)
    _final, seen = _poll_until_terminal(java_client, task["id"])

    stages = [stage for _status, stage, _progress in seen]
    assert set(stages) <= STAGE_SET, f"出现了契约外的 stage：{set(stages) - STAGE_SET}"
    missing = STAGE_SET - set(stages)
    assert not missing, f"这些 stage 没被观察到：{sorted(missing)}；实际序列={stages}"

    # 顺序单调：去掉相邻重复后必须是 parsing→splitting→embedding→summarizing→done 的前缀。
    deduped: list[str] = []
    for stage in stages:
        if not deduped or deduped[-1] != stage:
            deduped.append(stage)
    assert deduped == STAGES, f"stage 顺序不对：{deduped}"


def test_task_progress_is_monotonic(java_client, clean_db):
    """progress 只增不减，且落在 0..100。"""
    task, _doc = _start_rebuild(java_client, clean_db)
    _final, seen = _poll_until_terminal(java_client, task["id"])

    values = [progress for _status, _stage, progress in seen]
    assert all(isinstance(value, int) and 0 <= value <= 100 for value in values), values
    assert values == sorted(values), f"progress 出现回退：{values}"


def test_task_counts_match_documents_and_chunks(java_client, clean_db):
    """docCount 与资料数一致、chunkCount 与 /chunks 实际条数一致。"""
    task, _doc = _start_rebuild(java_client, clean_db)
    final, _seen = _poll_until_terminal(java_client, task["id"])

    assert final["docCount"] == 1, final

    docs = java_client.get("/api/v1/documents").json()["data"]
    assert len(docs) == final["docCount"], f"资料数 {len(docs)} != docCount {final['docCount']}"

    chunks_payload = java_client.get("/api/v1/chunks").json()
    chunks = chunks_payload["data"]
    if isinstance(chunks, dict):
        chunks = chunks["items"]
    assert len(chunks) == final["chunkCount"], f"片段数 {len(chunks)} != chunkCount {final['chunkCount']}"
    assert final["chunkCount"] > 0, "一份非空资料至少该切出一段"


def test_task_id_is_stable_across_polls(java_client, clean_db):
    """反复轮询同一个 id 拿到的是同一个任务（不是每次新建）。"""
    task, _doc = _start_rebuild(java_client, clean_db)
    first = java_client.get(f"/api/v1/index/tasks/{task['id']}").json()["data"]
    second = java_client.get(f"/api/v1/index/tasks/{task['id']}").json()["data"]

    assert first["id"] == second["id"] == task["id"], (first["id"], second["id"], task["id"])
    assert first["chunkSize"] == second["chunkSize"] == 180, (first, second)


def test_task_survives_service_restart_semantics(java_client, clean_db):
    """终态任务落库：再次查询仍是 SUCCEEDED（不是内存态）。

    这条守的是「任务表持久化」——如果任务只活在内存里，重启后前端刷新页面
    就会看到 40402，历史建库记录全丢。
    """
    task, _doc = _start_rebuild(java_client, clean_db)
    final, _seen = _poll_until_terminal(java_client, task["id"])
    assert final["status"] == "SUCCEEDED", final

    again = java_client.get(f"/api/v1/index/tasks/{task['id']}").json()["data"]
    assert again["status"] == "SUCCEEDED", again
    assert again["finishedAt"] == final["finishedAt"], (again, final)
