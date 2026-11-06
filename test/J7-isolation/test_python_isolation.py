"""J7 隔离门禁：Python 侧按 `X-User-Id` 隔离任务、文档、切片与索引清单。

为什么在进程内跑：这组断言检查的是「同一进程里两个用户互相看不见」，与 HTTP 传输无关。
用 TestClient 直连 ASGI，既不用起端口，也能精确构造「A 已建库、B 还没建库」的状态。
跨进程的真实链路（Java 登录两个账号 → 各自上传 → 互相读不到）在 `test_cross_user_http.py`。

契约要点（H2/H3）：

- 除 `health` 外，缺 `X-User-Id` 一律 400 / 40001，不存在「匿名就当 1 号用户」的兜底；
- `(user_id, submission_key)` 唯一：同一用户重试必须拿到同一个 `task_id`，不同用户同 key 互不影响；
- 跨用户查任务 → 40402，查文档 → 40401，两者都不能泄露「存在但不属于你」；
- 检索与索引清单只认本人最近一次成功任务；没建库的用户拿到空引用与 needs_rebuild，而不是别人的切片。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ai_app_loader import load_app

TOKEN = "j7-test-token"
USER_A = 101
USER_B = 202


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """独立 storage_root，保证每个用例从空库开始（SQLite 落在 tmp 里）。"""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    module = load_app(monkeypatch, TOKEN)
    with TestClient(module.app) as test_client:
        yield test_client


def headers(user: int, token: str = TOKEN) -> dict[str, str]:
    return {"X-Internal-Token": token, "X-User-Id": str(user)}


def parse_body(doc_id: str, text: str, key: str, generation: str = "g1") -> dict:
    return {
        "documents": [{"doc_id": doc_id, "name": f"{doc_id}.md", "title": doc_id, "text": text}],
        "chunk_size": 60,
        "overlap": 10,
        "submission_key": key,
        "generation": generation,
    }


def submit(client, user: int, body: dict) -> str:
    response = client.post("/internal/v1/documents/parse", json=body, headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()["data"]["task_id"]


def task_of(client, user: int, task_id: str) -> dict:
    response = client.get(f"/internal/v1/ingest/{task_id}", headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_missing_or_bad_user_header_is_rejected(client):
    """身份头缺失、非数字、非正数都按参数错误处理，不给任何默认用户。"""
    for value in (None, "", "abc", "0", "-3"):
        hdrs = {"X-Internal-Token": TOKEN}
        if value is not None:
            hdrs["X-User-Id"] = value
        response = client.get("/internal/v1/index/status", headers=hdrs)
        assert response.status_code == 400, (value, response.text)
        assert response.json()["code"] == 40001, (value, response.text)


def test_same_submission_key_returns_same_task(client):
    """重试（超时后重发）必须命中同一个任务，否则会并行建两代索引。"""
    first = submit(client, USER_A, parse_body("D-A1", "借阅规则：最多五本。", "sk-A-1"))
    second = submit(client, USER_A, parse_body("D-A1", "借阅规则：最多五本。", "sk-A-1"))
    assert first == second
    assert task_of(client, USER_A, first)["status"] == "SUCCEEDED"


def test_same_submission_key_different_users_are_independent(client):
    """幂等键的作用域是用户，不是全局；B 用 A 的 key 也必须拿到自己的任务。"""
    task_a = submit(client, USER_A, parse_body("D-A1", "A 的资料", "shared-key"))
    task_b = submit(client, USER_B, parse_body("D-B1", "B 的资料", "shared-key"))
    assert task_a != task_b
    assert task_of(client, USER_A, task_a)["doc_count"] == 1
    assert task_of(client, USER_B, task_b)["doc_count"] == 1


def test_cross_user_task_lookup_is_not_found(client):
    """跨用户查任务回 40402：既不返回数据，也不确认任务存在。"""
    task_a = submit(client, USER_A, parse_body("D-A1", "A 的资料", "sk-A"))
    response = client.get(f"/internal/v1/ingest/{task_a}", headers=headers(USER_B))
    assert response.status_code == 404, response.text
    assert response.json()["code"] == 40402


def test_cross_user_document_status_is_not_found(client):
    """跨用户查文档回 40401。"""
    submit(client, USER_A, parse_body("D-A1", "A 的资料", "sk-A"))
    response = client.get("/internal/v1/documents/D-A1/status", headers=headers(USER_B))
    assert response.status_code == 404, response.text
    assert response.json()["code"] == 40401


def test_retrieval_only_sees_own_chunks(client):
    """A 建库后，B 检索必须空；A 自己能检索到，且引用只来自自己的文档。"""
    submit(client, USER_A, parse_body("D-A1", "图书借阅上限为五本，借期三十天。", "sk-A"))

    mine = client.post(
        "/internal/v1/retrieve", json={"question": "借阅上限", "k": 3}, headers=headers(USER_A)
    ).json()["data"]
    assert mine["citations"], mine
    assert {row["doc_id"] for row in mine["citations"]} == {"D-A1"}

    theirs = client.post(
        "/internal/v1/retrieve", json={"question": "借阅上限", "k": 3}, headers=headers(USER_B)
    ).json()["data"]
    assert theirs["citations"] == [], theirs
    assert theirs["rows"] == [], theirs


def test_retrieval_never_fabricates_citations(client):
    """没有任何语料时返回空，而不是编一条看起来合理的引用。"""
    data = client.post(
        "/internal/v1/retrieve", json={"question": "随便问问", "k": 3}, headers=headers(USER_A)
    ).json()["data"]
    assert data["citations"] == []


def test_chat_stream_retrieval_is_scoped(client):
    """SSE 里的 retrieval 帧同样只含本人切片；B 的帧里必须是空列表。"""
    submit(client, USER_A, parse_body("D-A1", "逾期归还按天计费。", "sk-A"))

    body = {"question": "逾期怎么计费", "mode": "rag", "k": 3}
    own = client.post("/internal/v1/chat/stream", json=body, headers=headers(USER_A)).text
    other = client.post("/internal/v1/chat/stream", json=body, headers=headers(USER_B)).text

    own_citations = _citations(own)
    other_citations = _citations(other)
    assert own_citations, own
    assert other_citations == [], other


def _citations(sse_text: str) -> list[dict]:
    for block in sse_text.split("\n\n"):
        if block.startswith("event: retrieval"):
            payload = block.split("data:", 1)[1].strip()
            return json.loads(payload)["citations"]
    raise AssertionError(f"没有 retrieval 帧：{sse_text[:400]}")


def test_index_manifest_is_per_user(client):
    """A 建库后清单是 ready 且带真实切片参数；B 没建库，清单必须是 needs_rebuild。"""
    submit(client, USER_A, parse_body("D-A1", "x" * 300, "sk-A"))

    mine = client.get("/internal/v1/index/status", headers=headers(USER_A)).json()["data"]
    assert mine["status"] == "ready", mine
    assert mine["chunk_size"] == 60 and mine["overlap"] == 10, mine
    assert mine["doc_count"] == 1 and mine["chunk_count"] > 0, mine

    theirs = client.get("/internal/v1/index/status", headers=headers(USER_B)).json()["data"]
    assert theirs["status"] == "needs_rebuild", theirs
    assert theirs["chunk_count"] == 0 and theirs["doc_count"] == 0, theirs


def test_restart_marks_unfinished_tasks_failed(monkeypatch, tmp_path):
    """重启恢复：遗留的 PENDING/RUNNING 必须落成 FAILED，不能永远停在中间态。"""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    module = load_app(monkeypatch, TOKEN)

    from app.services import state  # noqa: PLC0415 - 必须在 load_app 之后导入

    with TestClient(module.app):
        task_id, created = state.create_task(USER_A, "sk-restart", "g1", 1, 60, 10)
        assert created
        assert state.get_task(USER_A, task_id)["status"] == "PENDING"
        state.update_task(USER_A, task_id, status="RUNNING", stage="splitting", progress=45)

    # 模拟进程重启：关连接 → 重新建表 → 恢复
    state.close()
    state.initialize()
    assert state.recover_interrupted() == 1
    recovered = state.get_task(USER_A, task_id)
    assert recovered["status"] == "FAILED"
    assert recovered["finished_at"] is not None
    assert state.RESTART_ERROR in recovered["error"]


def test_state_module_does_not_import_main():
    """H4 拆分约束：状态层不得反向依赖装配层，否则又会退回循环导入。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "server-ai" / "app"
    for name in ("services/state.py", "services/ingest.py", "services/chat.py", "api/routes.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from app.main" not in text and "import app.main" not in text, name
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "app.main" not in main
