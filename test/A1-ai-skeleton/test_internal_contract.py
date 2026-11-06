"""A1 内部接口契约：信封、内部令牌、用户身份头。

H2 之后所有用户态端点都要求 `X-User-Id`（缺失 → 400/40001），health 豁免；
`documents/parse` 还要求 `submission_key` / `generation`（H3 幂等键与代际）。
本文件用 `ai_app_loader.load_app` 起一个进程内 app，令牌走 monkeypatch 注入，
不依赖外部环境变量，也不写死开发用口令。
"""

from __future__ import annotations

import pytest

from ai_app_loader import load_app

TOKEN = "a1-internal-token"
USER = 7

ROUTES = [
    ("get", "/internal/v1/health", None),
    ("get", "/internal/v1/index/status", None),
    ("post", "/internal/v1/retrieve", {"question": "q"}),
    (
        "post",
        "/internal/v1/eval/batch",
        {"cases": [{"id": "T1", "question": "q", "keywords": "x"}], "mode": "both", "k": 1},
    ),
    (
        "post",
        "/internal/v1/documents/parse",
        {
            "documents": [{"doc_id": "d1", "name": "a.md", "text": "hello"}],
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-1",
            "generation": "g-1",
        },
    ),
]


def _headers(with_user: bool = True) -> dict[str, str]:
    headers = {"X-Internal-Token": TOKEN}
    if with_user:
        headers["X-User-Id"] = str(USER)
    return headers


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    module = load_app(monkeypatch, TOKEN)
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        yield client


def test_all_envelope_routes_authorized(client):
    for method, path, body in ROUTES:
        call = getattr(client, method)
        response = call(path, headers=_headers(), json=body) if body is not None else call(
            path, headers=_headers()
        )
        assert response.status_code == 200, (path, response.text)
        assert set(response.json()) == {"code", "message", "data", "timestamp"}


def test_chat_stream_authorized(client):
    response = client.post(
        "/internal/v1/chat/stream", headers=_headers(), json={"question": "q"}
    )
    assert response.status_code == 200
    assert "event: done" in response.text


def test_missing_token_is_401(client):
    response = client.get("/internal/v1/health")
    assert response.status_code == 401 and response.json()["code"] == 40102


def test_health_exempt_from_user_header(client):
    """探活是进程级接口，不该因为没带用户头而失败。"""
    response = client.get("/internal/v1/health", headers=_headers(with_user=False))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/internal/v1/index/status", "get", None),
        ("/internal/v1/retrieve", "post", {"question": "q"}),
    ],
)
def test_user_scoped_routes_reject_missing_user_header(client, path, method, body):
    call = getattr(client, method)
    response = call(path, headers=_headers(with_user=False), json=body) if body else call(
        path, headers=_headers(with_user=False)
    )
    assert response.status_code == 400, response.text
    assert response.json()["code"] == 40001


def test_parse_requires_submission_key_and_generation(client):
    for missing in ("submission_key", "generation"):
        payload = {
            "documents": [{"doc_id": "d1", "name": "a.md", "text": "hello"}],
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-1",
            "generation": "g-1",
        }
        payload.pop(missing)
        response = client.post(
            "/internal/v1/documents/parse", headers=_headers(), json=payload
        )
        assert response.status_code == 400, (missing, response.text)
        assert response.json()["code"] == 40001


def test_unknown_task_and_document_are_404(client):
    task = client.get("/internal/v1/ingest/missing", headers=_headers())
    assert task.status_code == 404 and task.json()["code"] == 40402
    document = client.get("/internal/v1/documents/missing/status", headers=_headers())
    assert document.status_code == 404 and document.json()["code"] == 40401


def test_validation_error_uses_envelope(client):
    response = client.post("/internal/v1/documents/parse", headers=_headers(), json={})
    assert response.status_code == 400
    assert set(response.json()) == {"code", "message", "data", "timestamp"}
    assert response.json()["code"] == 40001
