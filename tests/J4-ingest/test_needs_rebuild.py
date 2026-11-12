"""J4 门禁三：索引状态推导 + 片段浏览。

手册 §8「测试」第 3 条：`test_needs_rebuild.py`（改 chunkSize 不建库 → needs_rebuild 且文档
NEEDS_REBUILD；建库完成后 ready）。

契约关键点（docs/api/openapi-public.yaml:518-543、:473-514）：

- `GET /api/v1/index/status` 的 `unavailable` 是**成功响应（HTTP 200）**，不是 503 ——
  这条路由的 `x-error-codes` 只有 40100/50000。
- `GET /api/v1/chunks` 的 `q` 按正文子串匹配（**大小写敏感**），`kind` 按 chunk|summary|rule 过滤，
  三个参数可任意组合；返回数组（兼容 `{items}`）。
"""

from __future__ import annotations

import pytest

from conftest import wait_until

pytestmark = pytest.mark.live

STATUS_REQUIRED = {
    "status",
    "docCount",
    "chunkCount",
    "chunkSize",
    "overlap",
    "embeddingModel",
    "lastBuiltAt",
}
# 契约里 reason / manifest 是可选的（IndexStatus.required 只有 7 项），
# 但 additionalProperties: false 意味着不能出现这两个以外的多余字段。
STATUS_OPTIONAL = {"reason", "manifest"}
STATUS_VALUES = {"ready", "needs_rebuild", "unavailable"}
CHUNK_KEYS = {
    "chunkId",
    "docId",
    "docTitle",
    "headingPath",
    "text",
    "start",
    "end",
    "kind",
    "verified",
    "index",
}
KINDS = {"chunk", "summary", "rule"}


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


def _chunks(payload):
    data = payload["data"]
    return data if isinstance(data, list) else data["items"]


def _rebuild_and_wait(java_client, clean_db, chunk_size=180, overlap=30):
    """清库 → 上传一份资料 → 建库并等到成功，返回 (task, doc)。"""
    _clear_running(clean_db)
    doc = _upload(
        java_client,
        "j4_status.md",
        "# 借阅规则\n\n"
        "普通图书每人最多同时借阅 4 本，每本借期 21 天。\n\n"
        "续借一次增加 7 天，逾期不可续借。\n\n"
        "被他人预约的图书不能续借。\n",
    )
    resp = java_client.post(
        "/api/v1/index/rebuild", json={"chunkSize": chunk_size, "overlap": overlap}
    )
    assert resp.status_code == 200, resp.text
    task = resp.json()["data"]

    def _fetch():
        current = java_client.get(f"/api/v1/index/tasks/{task['id']}").json()["data"]
        return current if current["status"] in ("SUCCEEDED", "FAILED") else None

    final = wait_until(_fetch, timeout=15.0, message="建库未在 15s 内完成")
    return final, doc


def test_status_returns_contract_shape(java_client):
    """状态对象字段集与契约 IndexStatus 一致，且 status 在三个枚举值内。"""
    resp = java_client.get("/api/v1/index/status")
    payload = resp.json()

    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, payload
    status = payload["data"]
    # 契约 required 7 项必须齐；reason / manifest 可选，但不能出现这两者之外的字段
    # （additionalProperties: false 会因此校验失败）。
    assert STATUS_REQUIRED <= set(status), f"缺必填字段：{sorted(STATUS_REQUIRED - set(status))}"
    assert set(status) <= STATUS_REQUIRED | STATUS_OPTIONAL, (
        f"出现契约外字段：{sorted(set(status) - STATUS_REQUIRED - STATUS_OPTIONAL)}"
    )
    assert status["status"] in STATUS_VALUES, status
    assert isinstance(status["docCount"], int) and status["docCount"] >= 0, status
    assert isinstance(status["chunkCount"], int) and status["chunkCount"] >= 0, status
    assert 50 <= status["chunkSize"] <= 1000, status
    assert status["overlap"] >= 0, status
    assert isinstance(status["embeddingModel"], str) and status["embeddingModel"], status


def test_status_is_needs_rebuild_before_first_build(java_client, clean_db):
    """从未建库 → needs_rebuild，且 reason 说明原因。"""
    _clear_running(clean_db)
    _upload(java_client, "j4_never.md", "# 从未建库\n\n这份资料还没进过索引。\n")

    payload = java_client.get("/api/v1/index/status").json()
    status = payload["data"]

    assert status["status"] == "needs_rebuild", status
    assert isinstance(status["reason"], str) and status["reason"], status
    assert status["lastBuiltAt"] is None, status


def test_status_is_ready_after_successful_build(java_client, clean_db):
    """建库成功后 → ready，且 manifest 与本次参数一致。"""
    final, _doc = _rebuild_and_wait(java_client, clean_db)
    assert final["status"] == "SUCCEEDED", final

    payload = java_client.get("/api/v1/index/status").json()
    status = payload["data"]

    assert status["status"] == "ready", status
    assert status["chunkSize"] == 180, status
    assert status["overlap"] == 30, status
    assert isinstance(status["lastBuiltAt"], int) and status["lastBuiltAt"] > 0, status
    assert status["chunkCount"] == final["chunkCount"], (status, final)
    manifest = status.get("manifest")
    if manifest is not None:
        assert manifest["chunkSize"] == 180, manifest
        assert manifest["overlap"] == 30, manifest


def test_status_flips_to_needs_rebuild_after_new_upload(java_client, clean_db):
    """建库成功后再传一份资料 → needs_rebuild（语料变了，缓存不可信）。"""
    final, _doc = _rebuild_and_wait(java_client, clean_db)
    assert final["status"] == "SUCCEEDED", final
    assert java_client.get("/api/v1/index/status").json()["data"]["status"] == "ready"

    _upload(java_client, "j4_extra.md", "# 新增资料\n\n这份是建库之后才传的。\n")

    payload = java_client.get("/api/v1/index/status").json()
    status = payload["data"]
    assert status["status"] == "needs_rebuild", status
    assert isinstance(status["reason"], str) and status["reason"], status


def test_status_flips_to_needs_rebuild_after_param_change(java_client, clean_db):
    """用不同 chunkSize 再建库 → 状态先回 needs_rebuild，成功后再 ready。

    这条对应手册 §J4「改 chunkSize 不建库 → needs_rebuild」的等价场景：
    参数变了而缓存还是旧参数生成的，所以缓存必须被判脏。
    """
    final, _doc = _rebuild_and_wait(java_client, clean_db, chunk_size=180, overlap=30)
    assert final["status"] == "SUCCEEDED", final

    # 用新参数重建，成功前状态不该是 ready。
    resp = java_client.post("/api/v1/index/rebuild", json={"chunkSize": 200, "overlap": 20})
    assert resp.status_code == 200, resp.text
    new_task = resp.json()["data"]

    def _fetch():
        current = java_client.get(f"/api/v1/index/tasks/{new_task['id']}").json()["data"]
        return current if current["status"] in ("SUCCEEDED", "FAILED") else None

    second = wait_until(_fetch, timeout=15.0, message="第二次建库未在 15s 内完成")
    assert second["status"] == "SUCCEEDED", second
    assert second["chunkSize"] == 200, second

    payload = java_client.get("/api/v1/index/status").json()
    status = payload["data"]
    assert status["status"] == "ready", status
    assert status["chunkSize"] == 200, status
    assert status["overlap"] == 20, status


def test_status_doc_count_matches_documents(java_client, clean_db):
    """docCount 与 /documents 实际条数一致。"""
    _rebuild_and_wait(java_client, clean_db)

    docs = java_client.get("/api/v1/documents").json()["data"]
    status = java_client.get("/api/v1/index/status").json()["data"]
    assert status["docCount"] == len(docs), (status, docs)


def test_chunks_return_contract_shape(java_client, clean_db):
    """片段对象 10 个字段齐全（契约 ChunkItem，注意**没有 score**）。

    N3 之后列表里会混进摘要卡（`docId = "__summary__"`、`chunkId` 形如 `D00-C001`），
    它们不属于任何一份资料，所以 `docId == doc["id"]` 只对普通片段成立。
    """
    final, doc = _rebuild_and_wait(java_client, clean_db)
    assert final["chunkCount"] > 0, final

    payload = java_client.get("/api/v1/chunks").json()
    rows = _chunks(payload)
    assert rows, "建库成功后 /chunks 不该为空"

    for row in rows:
        assert set(row) == CHUNK_KEYS, f"字段集不对：{sorted(row)}"
        assert isinstance(row["chunkId"], str) and row["chunkId"], row
        assert row["chunkId"].startswith("D"), row
        if row["kind"] == "chunk":
            assert row["docId"] == doc["id"], (row, doc)
        else:
            # 摘要卡：docId 是哨兵字符串，编号固定 D00-*。
            assert row["docId"] == "__summary__", row
            assert row["chunkId"].startswith("D00-C"), row
        assert row["docTitle"], row
        assert isinstance(row["text"], str) and row["text"], row
        assert isinstance(row["start"], int) and row["start"] >= 0, row
        assert isinstance(row["end"], int) and row["end"] >= row["start"], row
        assert row["kind"] in KINDS, row
        assert isinstance(row["verified"], bool), row
        assert isinstance(row["index"], int) and row["index"] >= 0, row


def test_chunks_filter_by_doc_id(java_client, clean_db):
    """docId 精确过滤。"""
    final, doc = _rebuild_and_wait(java_client, clean_db)
    assert final["chunkCount"] > 0, final

    rows = _chunks(java_client.get(f"/api/v1/chunks?docId={doc['id']}").json())
    assert rows, "按本资料 id 过滤后不该为空"
    assert all(row["docId"] == doc["id"] for row in rows), rows

    empty = _chunks(java_client.get("/api/v1/chunks?docId=999999").json())
    assert empty == [], f"不存在的 docId 应回空数组：{empty}"


def test_chunks_filter_by_keyword_is_case_sensitive(java_client, clean_db):
    """`q` 是大小写敏感的子串匹配（契约 description 原文）。"""
    final, _doc = _rebuild_and_wait(java_client, clean_db)
    assert final["chunkCount"] > 0, final

    hits = _chunks(java_client.get("/api/v1/chunks?q=21").json())
    assert hits, "正文里有「21 天」，按 21 过滤不该为空"
    assert all("21" in row["text"] for row in hits), hits

    misses = _chunks(java_client.get("/api/v1/chunks?q=不存在的关键词ZZZ").json())
    assert misses == [], f"匹配不到应回空数组：{misses}"


def test_chunks_filter_by_kind(java_client, clean_db):
    """kind 过滤：三个取值各自只回本类片段。

    N3 之后 mock 档也会产出摘要卡（统计卡 + 规则卡），所以 `kind=rule` 不再是空数组 ——
    旧断言「mock 不产 rule」写于 N3 之前。
    """
    final, _doc = _rebuild_and_wait(java_client, clean_db)
    assert final["chunkCount"] > 0, final

    chunk_rows = _chunks(java_client.get("/api/v1/chunks?kind=chunk").json())
    assert chunk_rows, "普通片段必须有"
    assert all(row["kind"] == "chunk" for row in chunk_rows), chunk_rows

    rule_rows = _chunks(java_client.get("/api/v1/chunks?kind=rule").json())
    assert rule_rows, "N3 之后 mock 档会产出规则卡"
    assert all(row["kind"] == "rule" for row in rule_rows), rule_rows
    assert all(row["docId"] == "__summary__" for row in rule_rows), rule_rows

    summary_rows = _chunks(java_client.get("/api/v1/chunks?kind=summary").json())
    assert summary_rows, "N3 之后 mock 档会产出统计卡"
    assert all(row["kind"] == "summary" for row in summary_rows), summary_rows


def test_chunks_filters_combine(java_client, clean_db):
    """三个过滤参数可任意组合，且是「与」关系。"""
    final, doc = _rebuild_and_wait(java_client, clean_db)
    assert final["chunkCount"] > 0, final

    both = _chunks(java_client.get(f"/api/v1/chunks?docId={doc['id']}&kind=chunk").json())
    assert both, "docId + kind 组合应有结果"

    contradictory = _chunks(
        java_client.get(f"/api/v1/chunks?docId={doc['id']}&kind=rule").json()
    )
    assert contradictory == [], f"docId 与 kind=rule 组合应为空：{contradictory}"


def test_chunks_empty_before_first_build(java_client, clean_db):
    """从未建库时 /chunks 回空数组而不是 404 / 50101。"""
    _clear_running(clean_db)
    payload = java_client.get("/api/v1/chunks").json()

    assert payload["code"] == 0, payload
    assert _chunks(payload) == [], payload
