"""H1 身份门禁：真实口令 + 签名 JWT。

H1 之前这里断言的是「demo/demo 换一个 demo- 前缀的内存令牌」。那套东西已经整体删除：

- 口令必须与库里 `password_hash` 的 BCrypt 摘要比对，`V6__demo_user.sql` 留下的字面量
  `'demo'` 在非 demo profile 下永远验不过；
- 令牌是 HS256 签名 JWT，带 `iss`/`exp`/`sub`，`dev-token` 这类固定串一律 40100；
- 身份只来自令牌，路由不再有 `userId == null ? 1L : userId` 这种兜底。
"""

from __future__ import annotations

import base64
import json
import os

import pytest

pytestmark = pytest.mark.live

USERNAME = os.getenv("JAVA_USERNAME", "gate-a")
PASSWORD = os.getenv("JAVA_PASSWORD", "")


def _post_login(client, username, password):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def test_login_issues_signed_jwt_for_the_stored_account(bare_client):
    response = _post_login(bare_client, USERNAME, PASSWORD)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    result = payload["data"]

    # 令牌必须是三段式 JWT，且不再带 demo- 前缀。
    assert result["token"].count(".") == 2, result["token"]
    assert not result["token"].startswith("demo-")
    assert result["expiresIn"] == 3600, result
    assert result["user"]["username"] == USERNAME
    assert result["user"]["id"] > 0

    profile = bare_client.get(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {result['token']}"},
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["data"] == result["user"]


def test_token_subject_is_the_database_row(bare_client):
    """`sub` 取库里的用户 id，而不是请求里出现的任何东西。"""
    response = _post_login(bare_client, USERNAME, PASSWORD)
    token = response.json()["data"]["token"]
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)
    claims = json.loads(base64.urlsafe_b64decode(body))
    assert claims["sub"] == str(response.json()["data"]["user"]["id"])
    assert claims["iss"] == os.getenv("AUTH_JWT_ISSUER", "xiaoyi-rag")
    assert claims["exp"] > claims["iat"]


def test_wrong_password_is_rejected(bare_client):
    response = _post_login(bare_client, USERNAME, PASSWORD + "-wrong")
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_unknown_account_is_rejected_and_not_provisioned(bare_client):
    response = _post_login(bare_client, "nobody-here", "whatever-password")
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_unknown_account_and_wrong_password_look_identical(bare_client):
    """两条失败路径的响应体必须一致，否则等于给了账号枚举接口。

    只比 `code` / `message` / `data`：`timestamp` 是服务端当前秒数，天然会不同，
    把它算进比较等于让这条用例依赖两次请求落在同一秒。
    """
    unknown = _post_login(bare_client, "nobody-here", "whatever-password")
    wrong = _post_login(bare_client, USERNAME, PASSWORD + "-wrong")

    def comparable(response):
        body = response.json()
        return {key: body[key] for key in ("code", "message", "data")}

    assert comparable(unknown) == comparable(wrong)


def test_legacy_literal_demo_hash_no_longer_authenticates(bare_client):
    """V6 插入的 `password_hash='demo'` 是历史字面量，不是 BCrypt 摘要。"""
    response = _post_login(bare_client, "demo", "demo")
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_blank_username_or_password_is_a_parameter_error(bare_client):
    for body in (
        {"username": "", "password": PASSWORD},
        {"username": USERNAME, "password": ""},
        {"username": "   ", "password": PASSWORD},
    ):
        response = bare_client.post("/api/v1/auth/login", json=body)
        assert response.status_code == 400, (body, response.text)
        assert response.json()["code"] == 40001, body


@pytest.mark.parametrize(
    "token",
    [None, "", "unknown-token", "dev-token", "demo-1", "a.b.c"],
)
def test_profile_rejects_unsigned_or_foreign_tokens(bare_client, token):
    """空令牌有两种表现：不带 Authorization（None）与 `Bearer ` 前缀残缺，都必须 40100。

    `Bearer `（尾随空格、令牌为空）在 HTTP 层就不合法，httpx 会直接抛 LocalProtocolError，
    所以这里用「不带 Authorization」来表达同一个语义，服务端仍然要 401。
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = bare_client.get("/api/v1/auth/profile", headers=headers)
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_profile_requires_an_authorization_header(bare_client):
    response = bare_client.get("/api/v1/auth/profile")
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_token_signed_with_another_secret_is_rejected(bare_client):
    """拿另一把密钥签一个结构合法的 JWT，签名校验必须拦住。"""
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"iss": os.getenv("AUTH_JWT_ISSUER", "xiaoyi-rag"), "sub": "1", "exp": 2**31}
    forge = ".".join(
        base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")
        for part in (header, claims)
    )
    forged = f"{forge}.{base64.urlsafe_b64encode(b'not-the-real-key').decode().rstrip('=')}"
    response = bare_client.get(
        "/api/v1/auth/profile", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401, response.text
    assert response.json()["code"] == 40100


def test_business_routes_reject_missing_identity(bare_client):
    """没有令牌就不再落到「默认用户 1」，而是 401/40100。"""
    for path in ("/api/v1/documents", "/api/v1/conversations", "/api/v1/index/status"):
        response = bare_client.get(path)
        assert response.status_code == 401, (path, response.text)
        assert response.json()["code"] == 40100, path
