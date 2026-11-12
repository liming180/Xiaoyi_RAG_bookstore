"""J1 骨架门禁：健康检查。

手册 §5「测试（test/J1-skeleton/ 下写）」第 1 条：
GET /actuator/health 与 /api/v1/health 均 200 且信封 code=0。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


def test_business_health_returns_ok_envelope(java_client):
    """GET /api/v1/health 返回 200 + 标准信封 + data.status == 'UP'。"""
    resp = java_client.get("/api/v1/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"code", "message", "data", "timestamp"}, body
    assert body["code"] == 0, body
    assert body["data"] == {"status": "UP"}, body
    assert isinstance(body["timestamp"], int), "timestamp 必须是整数 Unix 秒"
    assert body["timestamp"] > 1_600_000_000, "timestamp 明显不是秒级时间戳"


def test_actuator_health_is_up(java_client):
    """GET /actuator/health 返回 200 且 status == 'UP'。"""
    resp = java_client.get("/actuator/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "UP", body


def test_health_needs_no_token(bare_client):
    """健康检查是白名单，不带 Authorization 也要 200。"""
    resp = bare_client.get("/api/v1/health")

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
