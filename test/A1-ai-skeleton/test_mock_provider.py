"""A1 内部契约：Mock provider 的 SSE 事件序列。

H2 之后 chat 端点要求 `X-User-Id`，且检索只取该用户最近一次成功任务的切片。
本文件走 `ai_app_loader` 起进程内 app，不依赖外部环境变量。
"""

from __future__ import annotations

import json

import pytest

from ai_app_loader import load_app

TOKEN = "a1-internal-token"
USER = 7


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    module = load_app(monkeypatch, TOKEN)
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        yield client


def _events(text: str) -> list[tuple[str | None, dict]]:
    events: list[tuple[str | None, dict]] = []
    current = None
    for line in text.splitlines():
        if line.startswith("event: "):
            current = line[7:]
        elif line.startswith("data: "):
            events.append((current, json.loads(line[6:])))
    return events


def test_mock_stream_has_contract_events(client):
    response = client.post(
        "/internal/v1/chat/stream",
        headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
        json={"question": "借阅规则"},
    )
    assert response.status_code == 200, response.text

    events = _events(response.text)
    kinds = [event[0] for event in events]
    assert kinds[0:3] == ["status", "status", "status"]
    assert "retrieval" in kinds and "token" in kinds and kinds[-1] == "done"

    done = events[-1][1]
    assert "usage" in done and "elapsed_ms" in done
    assert done["message_id"].startswith("py-m-")


def test_stream_retrieval_is_empty_without_own_corpus(client):
    """没有任何成功建库任务时，retrieval 帧必须是空列表，不能编造引用。"""
    response = client.post(
        "/internal/v1/chat/stream",
        headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
        json={"question": "借阅规则"},
    )
    events = _events(response.text)
    retrieval = [data for kind, data in events if kind == "retrieval"]
    assert retrieval, events
    assert retrieval[0]["citations"] == []
