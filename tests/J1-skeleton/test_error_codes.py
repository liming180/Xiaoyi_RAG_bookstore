"""J1 骨架门禁：错误码与 HTTP 状态码的对应。

手册 §5「测试（test/J1-skeleton/ 下写）」第 3 条：
造 400（参数校验）、401（无 token 访问受保护路径）、409、503 四类，断言 code 与 HTTP 状态码。

400 / 401 走真实业务路径（空 body 触发 @Valid、缺 Authorization 触发拦截器）。

409 / 503 在 J1 骨架里没有真实业务能产生（实验并发、建库任务并发、AI 不可用都要等
J4 / J6），所以由 `GateProbeController`（仅在 `gate-probe` profile 下注册）提供
`GET /__gate/throw?code=NNNNN` 端点，把错误码真抛一遍，走同一条
`GlobalExceptionHandler` 分支。起服务时必须带 `--spring.profiles.active=gate-probe`，
否则这些用例会以明确的失败信息提示你去加 profile。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
ERROR_CODE_SRC = (
    REPO_ROOT / "server-java/src/main/java/com/xiaoyi/rag/common/enums/ErrorCode.java"
)
HANDLER_SRC = (
    REPO_ROOT
    / "server-java/src/main/java/com/xiaoyi/rag/common/exception/GlobalExceptionHandler.java"
)

#: 起服务时没加 `gate-probe` profile 的提示。
PROBE_HINT = (
    "门禁探针未注册。请用 `--spring.profiles.active=gate-probe` 启动服务：\n"
    "  java -jar server-java/target/xiaoyi-rag-server-0.1.0-SNAPSHOT.jar "
    "--spring.profiles.active=gate-probe"
)


def test_missing_body_field_returns_40001_with_http_400(java_client):
    """POST /api/v1/auth/login 空 body → MethodArgumentNotValidException → 40001 / 400。"""
    resp = java_client.post("/api/v1/auth/login", json={})

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == 40001, body
    assert body["data"] is None
    assert set(body) == {"code", "message", "data", "timestamp"}, body


def test_rebuild_with_invalid_chunk_size_returns_40002(java_client):
    """chunkSize 越界 → 40002 / 400（业务校验，不是 Bean Validation 的 40001）。

    J1 骨架阶段这条端点还是 `throw new ApiException(50101)`，越界由 `@Min/@Max` 先拦成 40001；
    J4 把 `@Min/@Max` 从 `RebuildRequest` 上摘掉后，区间判定搬进 `IndexServiceImpl.validate`，
    按 `docs/api/error-codes.md:79` 的拍板回 40002。这里断言的是**契约**，不是框架行为。
    """
    resp = java_client.post("/api/v1/index/rebuild", json={"chunkSize": 10, "overlap": 0})

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == 40002, body
    assert "50" in body["message"] and "1000" in body["message"], body["message"]
    assert body["data"] is None
    assert set(body) == {"code", "message", "data", "timestamp"}, body


def test_malformed_json_returns_40001(java_client):
    """请求体不是合法 JSON → HttpMessageNotReadableException → 40001 / 400。"""
    resp = java_client.post(
        "/api/v1/chat/stream",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40001


def test_protected_route_without_token_returns_40100(bare_client):
    """不带 Authorization 访问受保护路径 → 40100 / 401。"""
    resp = bare_client.get("/api/v1/conversations")

    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert set(body) == {"code", "message", "data", "timestamp"}, body
    assert body["code"] == 40100, body
    assert body["data"] is None


def test_protected_route_with_blank_token_returns_40100(bare_client):
    """Bearer 后面没有 token 也算未认证。

    httpx 会拒发值为 "Bearer "（尾随空格）的头，所以这里发 "Bearer"，
    服务端按 `startsWith("Bearer ")` 判定同样走 40100 分支。
    """
    resp = bare_client.get(
        "/api/v1/conversations",
        headers={"Authorization": "Bearer"},
    )

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 40100


def test_protected_route_with_wrong_scheme_returns_40100(bare_client):
    """非 Bearer 方案（如 Basic）同样拒绝。"""
    resp = bare_client.get(
        "/api/v1/conversations",
        headers={"Authorization": "Basic YWRtaW46YWRtaW4="},
    )

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 40100


def test_write_route_without_token_returns_40100(bare_client):
    """写接口同样受保护，且拦截发生在 Controller 之前（不会先 501）。"""
    resp = bare_client.post("/api/v1/conversations", json={"title": "t"})

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 40100


# --------------------------------------------------------------- 409 / 503 真实运行时验证


@pytest.mark.parametrize(
    "code,http_status,message_keyword",
    [
        (40901, 409, "实验"),
        (40902, 409, "实验"),
        (40903, 409, "建库"),
        (50301, 503, "AI"),
        (50101, 501, "尚未实现"),
        (50001, 500, "模型"),
        (50000, 500, "内部"),
        (40102, 401, "令牌"),
        (40401, 404, "资料"),
        (40407, 404, "消息"),
    ],
)
def test_probe_throws_documented_code_with_matching_http_status(
    java_client, code, http_status, message_keyword
):
    """探针抛码 → GlobalExceptionHandler → HTTP 状态码与 code 同步。

    这条用例覆盖手册要求的 409 / 503 两类，顺带把 404 / 500 / 501 也验一遍，
    保证 `ErrorCode.statusOf` 与 `Result.fail` 的组合在所有分支上一致。
    """
    resp = java_client.get("/__gate/throw", params={"code": code})

    # 探针没注册时 Spring 会回默认 404 白页（不是信封），据此区分「探针缺失」
    # 与「业务真的返回 404」——后者 body 是标准信封且 code 就是 404xx。
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
    if body is None or set(body) != {"code", "message", "data", "timestamp"}:
        pytest.fail(f"{PROBE_HINT}\n实际响应：HTTP {resp.status_code} {resp.text[:200]}")

    assert resp.status_code == http_status, resp.text
    assert body["code"] == code, body
    assert body["data"] is None, body
    assert message_keyword in body["message"], body["message"]


def test_probe_rejects_unregistered_code_as_40001(java_client):
    """未登记的错误码不许穿透，统一降级成 40001。"""
    resp = java_client.get("/__gate/throw", params={"code": 49999})

    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
    if body is None or set(body) != {"code", "message", "data", "timestamp"}:
        pytest.fail(f"{PROBE_HINT}\n实际响应：HTTP {resp.status_code} {resp.text[:200]}")

    assert resp.status_code == 400, resp.text
    assert body["code"] == 40001


# --------------------------------------------------------------------- 源码级一致性


def test_error_code_enum_exists_and_covers_all_documented_codes():
    """ErrorCode 枚举必须覆盖 docs/api/error-codes.md 里的 21 个码。"""
    md = (REPO_ROOT / "docs/api/error-codes.md").read_text(encoding="utf-8")
    documented = {
        int(m) for m in re.findall(r"^\|\s*`(\d{4,5})`\s*\|", md, flags=re.MULTILINE)
    }
    assert len(documented) == 21, f"错误码文档应有 21 个码，实际 {len(documented)}"

    src = ERROR_CODE_SRC.read_text(encoding="utf-8")
    declared = {int(m) for m in re.findall(r"\b[A-Z_]+\((\d{4,5}),", src)}
    missing = documented - declared
    assert not missing, f"ErrorCode 枚举缺这些码：{sorted(missing)}"


@pytest.mark.parametrize(
    "name,code,http_constant",
    [
        ("EXPERIMENT_BUSY", 40901, "CONFLICT"),
        ("EXPERIMENT_ALREADY_RUNNING", 40902, "CONFLICT"),
        ("INDEX_TASK_ALREADY_RUNNING", 40903, "CONFLICT"),
        ("AI_UNAVAILABLE", 50301, "SERVICE_UNAVAILABLE"),
        ("NOT_IMPLEMENTED", 50101, "NOT_IMPLEMENTED"),
        ("INTERNAL_ERROR", 50000, "INTERNAL_SERVER_ERROR"),
        ("UNAUTHENTICATED", 40100, "UNAUTHORIZED"),
        ("INVALID_PARAM", 40001, "BAD_REQUEST"),
    ],
)
def test_error_code_enum_maps_http_status(name, code, http_constant):
    """409/503/501/500/401/400 六类码必须显式绑定到对应 HttpStatus。"""
    src = ERROR_CODE_SRC.read_text(encoding="utf-8")
    pattern = rf"{name}\(\s*{code}\s*,[^)]*HttpStatus\.{http_constant}"
    assert re.search(pattern, src), f"{name}({code}) 未绑定 HttpStatus.{http_constant}"


def test_global_handler_routes_through_error_code_table():
    """GlobalExceptionHandler 必须靠 ErrorCode.statusOf 决定 HTTP 码，不能硬编码。"""
    src = HANDLER_SRC.read_text(encoding="utf-8")
    assert "ErrorCode.statusOf" in src, "GlobalExceptionHandler 未使用 ErrorCode.statusOf"
    assert "RestControllerAdvice" in src
    assert "50000" in src or "INTERNAL_ERROR" in src, "缺少兜底 50000 分支"

