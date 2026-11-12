"""J6 内部契约：令牌、用户头、信封、SSE 形状与部署拓扑。

H2 起内部接口分两类身份：

- `X-Internal-Token`：进程间共享密钥，8 条路由全部要求；
- `X-User-Id`：Java 注入的可信用户范围，除 `health` 外的 7 条用户态路由全部要求。

因此本文件的请求必须同时带两个头；只带令牌会被 40001 拒绝，这是 H2 的 fail-closed 语义。
"""

from __future__ import annotations

import pytest
from conftest import REPO_ROOT
from fastapi.testclient import TestClient

from server_ai_loader import load_app

TOKEN = "j6-test-token"
USER = 7


@pytest.fixture()
def client(monkeypatch):
    module = load_app(monkeypatch, TOKEN)
    with TestClient(module.app) as test_client:
        yield test_client


def headers(token: str = TOKEN, user: int | None = USER):
    """内部令牌 + 用户范围；`user=None` 只用于验证缺头被拒。"""
    result = {"X-Internal-Token": token}
    if user is not None:
        result["X-User-Id"] = str(user)
    return result


def test_all_internal_routes_require_token(client):
    checks = [
        ("get", "/internal/v1/health", None),
        ("get", "/internal/v1/index/status", None),
        ("get", "/internal/v1/ingest/missing", None),
        ("get", "/internal/v1/documents/missing/status", None),
        ("post", "/internal/v1/retrieve", {"k": 1}),
        (
            "post",
            "/internal/v1/eval/batch",
            {"cases": [{"id": "T1", "question": "q", "keywords": "q"}], "mode": "rag", "k": 1},
        ),
        (
            "post",
            "/internal/v1/documents/parse",
            {
                "documents": [{"doc_id": "D1", "text": "text"}],
                "chunk_size": 100,
                "overlap": 10,
                "submission_key": "sk-token",
                "generation": "g1",
            },
        ),
        ("post", "/internal/v1/chat/stream", {"question": "hello", "mode": "rag", "k": 1}),
    ]
    for method, path, body in checks:
        kwargs = {"headers": {"X-Internal-Token": "wrong", "X-User-Id": str(USER)}}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["code"] == 40102


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/internal/v1/index/status", None),
        ("get", "/internal/v1/ingest/missing", None),
        ("get", "/internal/v1/documents/missing/status", None),
        ("post", "/internal/v1/retrieve", {"k": 1}),
        ("post", "/internal/v1/chat/stream", {"question": "hello", "mode": "rag", "k": 1}),
    ],
)
def test_user_scoped_routes_reject_missing_user_header(client, method, path, body):
    """用户态路由缺 `X-User-Id` → 400 / 40001，绝不放行成匿名或默认用户。"""
    kwargs = {"headers": {"X-Internal-Token": TOKEN}}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 400, (method, path, response.text)
    assert response.json()["code"] == 40001


def test_health_exempt_from_user_header(client):
    """探活是进程级的，不该被用户头绑架。"""
    response = client.get("/internal/v1/health", headers=headers(user=None))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "UP"


def test_chat_sse_and_internal_shapes(client):
    response = client.post(
        "/internal/v1/chat/stream",
        json={"question": "hello", "mode": "rag", "k": 1},
        headers=headers(),
    )
    assert response.status_code == 200
    assert "event: status" in response.text
    assert "event: retrieval" in response.text
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert '"message_id"' in response.text
    assert '"elapsed_ms"' in response.text


def test_parse_ingest_retrieve_document_index_health(client):
    response = client.post(
        "/internal/v1/documents/parse",
        json={
            "documents": [{"doc_id": "D-J6", "name": "j6.md", "text": "hello"}],
            "chunk_size": 100,
            "overlap": 10,
            "submission_key": "sk-j6",
            "generation": "gen-j6",
        },
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["data"]["task_id"]
    assert (
        client.get(f"/internal/v1/ingest/{task_id}", headers=headers()).json()["data"]["task_id"]
        == task_id
    )
    assert (
        client.get("/internal/v1/documents/D-J6/status", headers=headers()).json()["data"]["doc_id"]
        == "D-J6"
    )
    assert client.post(
        "/internal/v1/retrieve", json={"question": "hello", "k": 1}, headers=headers()
    ).json()["data"]["citations"]
    assert client.get("/internal/v1/index/status", headers=headers()).status_code == 200
    assert client.get("/internal/v1/health", headers=headers()).json()["data"]["status"] == "UP"


def test_validation_is_enveloped(client):
    response = client.post("/internal/v1/retrieve", json={"k": 0}, headers=headers())
    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_parse_requires_submission_key_and_generation(client):
    """幂等键与代际是 H3 的契约基础，缺任一项都必须被挡在入口。"""
    base = {
        "documents": [{"doc_id": "D-J6b", "name": "b.md", "text": "hello"}],
        "chunk_size": 100,
        "overlap": 10,
    }
    for missing in ("submission_key", "generation"):
        body = dict(base)
        body["submission_key"] = "sk"
        body["generation"] = "g"
        body.pop(missing)
        response = client.post("/internal/v1/documents/parse", json=body, headers=headers())
        assert response.status_code == 400, (missing, response.text)
        assert response.json()["code"] == 40001


def test_compose_has_four_services_and_private_python():
    # 用 conftest 的 REPO_ROOT 而不是相对路径：pytest 可能从 test/ 目录启动（tools/p7_pytest.py），
    # 相对 "deploy/..." 会解析到 test/deploy 而报 FileNotFoundError。
    compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert all(f"  {name}:" in compose for name in ("frontend", "java-backend", "python-ai", "mysql"))
    python_block = compose.split("  python-ai:", 1)[1].split("  java-backend:", 1)[0]
    assert "ports:" not in python_block
    assert "python-ai:8000" in compose
    # H4 之后 main.py 只装配，令牌校验落在 api/deps.py。
    assert (
        "X-Internal-Token"
        in (REPO_ROOT / "server-ai" / "app" / "api" / "deps.py").read_text(encoding="utf-8")
    )
