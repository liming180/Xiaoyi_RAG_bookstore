"""演示模式 login/profile 的行为门禁。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


def test_login_returns_demo_token_and_user(java_client):
    response = java_client.post(
        "/api/v1/auth/login", json={"username": "demo", "password": "demo"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    result = payload["data"]
    assert result["token"].startswith("demo-")
    assert result["expiresIn"] == 86400
    assert result["user"] == {"id": 1, "username": "demo", "displayName": "演示用户"}

    profile = java_client.get(
        "/api/v1/auth/profile", headers={"Authorization": f"Bearer {result['token']}"}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["data"] == result["user"]


def test_login_rejects_blank_username(java_client):
    response = java_client.post(
        "/api/v1/auth/login", json={"username": "", "password": "demo"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_profile_rejects_unknown_token(java_client):
    response = java_client.get(
        "/api/v1/auth/profile", headers={"Authorization": "Bearer unknown-token"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == 40100
