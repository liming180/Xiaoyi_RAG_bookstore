from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server_ai_loader import load_app

TOKEN = "j6-test-token"


@pytest.fixture()
def client(monkeypatch):
    module = load_app(monkeypatch, TOKEN)
    with TestClient(module.app) as test_client:
        yield test_client


def headers(token: str = TOKEN):
    return {"X-Internal-Token": token}


def test_all_internal_routes_require_token(client):
    checks = [
        ("get", "/internal/v1/health", None),
        ("get", "/internal/v1/index/status", None),
        ("get", "/internal/v1/ingest/missing", None),
        ("get", "/internal/v1/documents/missing/status", None),
        ("post", "/internal/v1/retrieve", {"k": 1}),
        ("post", "/internal/v1/eval/batch", {"cases": [{"id": "T1", "question": "q", "keywords": "q"}], "mode": "rag", "k": 1}),
        ("post", "/internal/v1/documents/parse", {"documents": [{"doc_id": "D1", "text": "text"}], "chunk_size": 100, "overlap": 10}),
        ("post", "/internal/v1/chat/stream", {"question": "hello", "mode": "rag", "k": 1}),
    ]
    for method, path, body in checks:
        kwargs = {"headers": {"X-Internal-Token": "wrong"}}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["code"] == 40102


def test_chat_sse_and_internal_shapes(client):
    response = client.post("/internal/v1/chat/stream", json={"question": "hello", "mode": "rag", "k": 1}, headers=headers())
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
        json={"documents": [{"doc_id": "D-J6", "name": "j6.md", "text": "hello"}], "chunk_size": 100, "overlap": 10},
        headers=headers(),
    )
    assert response.status_code == 200
    task_id = response.json()["data"]["task_id"]
    assert client.get(f"/internal/v1/ingest/{task_id}", headers=headers()).json()["data"]["task_id"] == task_id
    assert client.get("/internal/v1/documents/D-J6/status", headers=headers()).json()["data"]["doc_id"] == "D-J6"
    assert client.post("/internal/v1/retrieve", json={"question": "hello", "k": 1}, headers=headers()).json()["data"]["citations"]
    assert client.get("/internal/v1/index/status", headers=headers()).status_code == 200
    assert client.get("/internal/v1/health", headers=headers()).json()["data"]["status"] == "UP"


def test_validation_is_enveloped(client):
    response = client.post("/internal/v1/retrieve", json={"k": 0}, headers=headers())
    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_compose_has_four_services_and_private_python():
    compose = Path("deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert all(f"  {name}:" in compose for name in ("frontend", "java-backend", "python-ai", "mysql"))
    python_block = compose.split("  python-ai:", 1)[1].split("  java-backend:", 1)[0]
    assert "ports:" not in python_block
    assert "python-ai:8000" in compose
    assert "X-Internal-Token" in Path("server-ai/app/main.py").read_text(encoding="utf-8")
