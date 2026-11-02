"""J1 骨架门禁：28 条对外路由的信封形状。

手册 §5「测试（test/J1-skeleton/ 下写）」第 2 条：
遍历 28 条路由，未实现的必须回 50101 且 HTTP 200/501 带完整信封（不能是 Spring 默认白页）。

对齐关系：

- 28 条清单取自 docs/api/openapi-public.yaml 的 operationId 全集，
  与 test/J0-contract/test_openapi_public_valid.py 的 EXPECTED_OPERATIONS 一致。
- J1 阶段只有 login 会因参数校验返回 40001（admin/password 是合法请求体，
  所以这里用空 body 触发校验），/api/v1/health 是唯一真实现。

随阶段推进的调整：

- J2：9 条 CRUD 真落库（会话 5 条 + 文档 4 条），从「必须 50101」的清单里剔除，
  改由 J2-crud 用例验行为；这里只保留「信封形状」校验，防止它们退化成 Spring 默认错误页。
- J3：`getMessageTrace` 也实现了（不存在/无轨迹都回标准信封），移入已实现清单；
  `chatStream` 是 SSE 端点，响应体不是信封而是事件流，所以单列一张 STREAM_ROUTE 表，
  只验「校验失败时回的是信封」——流本身由 test/J3-sse 覆盖。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse

pytestmark = pytest.mark.live

# operationId -> (method, path, body)
# body 为 None 表示不带请求体；有 body 的都发合法 JSON，好让请求真正进到 Controller 里。
PENDING_ROUTES = [
    ("login", "POST", "/api/v1/auth/login", {"username": "admin", "password": "x"}),
    ("getProfile", "GET", "/api/v1/auth/profile", None),
    ("listChunks", "GET", "/api/v1/chunks", None),
    ("getIndexStatus", "GET", "/api/v1/index/status", None),
    ("rebuildIndex", "POST", "/api/v1/index/rebuild", {"chunkSize": 300, "overlap": 50}),
    ("getIndexTask", "GET", "/api/v1/index/tasks/1", None),
    ("listEvalQuestions", "GET", "/api/v1/eval/questions", None),
    ("startEvalBatch", "POST", "/api/v1/eval/batch", {"mode": "both", "k": 3}),
    ("listEvalRuns", "GET", "/api/v1/eval/runs", None),
    ("getEvalRun", "GET", "/api/v1/eval/runs/1", None),
    ("submitFeedback", "POST", "/api/v1/messages/1/feedback", {"rating": "up"}),
    ("getFeedbackSummary", "GET", "/api/v1/feedback/summary", None),
    ("listEvalCandidates", "GET", "/api/v1/eval/candidates", None),
    ("decideEvalCandidate", "POST", "/api/v1/eval/candidates/1/decision", {"status": "accepted"}),
    ("createExperiment", "POST", "/api/v1/eval/experiments", {"name": "e"}),
    ("getExperiment", "GET", "/api/v1/eval/experiments/1", None),
    ("getExperimentReport", "GET", "/api/v1/eval/experiments/1/report", None),
]

# J2 / J3 已实现的 9 条：只验信封形状，具体行为由 test/J2-crud、test/J3-sse 覆盖。
IMPLEMENTED_ROUTES = [
    ("listConversations", "GET", "/api/v1/conversations", None),
    ("createConversation", "POST", "/api/v1/conversations", {"title": "信封形状校验"}),
    ("deleteConversation", "DELETE", "/api/v1/conversations/999999", None),
    ("listMessages", "GET", "/api/v1/conversations/999999/messages", None),
    ("clearMessages", "DELETE", "/api/v1/conversations/999999/messages", None),
    ("listDocuments", "GET", "/api/v1/documents", None),
    ("updateDocument", "PUT", "/api/v1/documents/999999", {"title": "t"}),
    ("deleteDocument", "DELETE", "/api/v1/documents/999999", None),
    ("getMessageTrace", "GET", "/api/v1/messages/999999/trace", None),
]

# 需要 multipart 单独处理的上传接口，不放进 ROUTES 的 JSON 遍历。
UPLOAD_ROUTE = ("uploadDocuments", "POST", "/api/v1/documents")

# SSE 端点：响应体不是信封，单独一张表。
STREAM_ROUTE = ("chatStream", "POST", "/api/v1/chat/stream")


def _call(client, method, path, body):
    if body is None:
        return client.request(method, path)
    return client.request(method, path, json=body)


def _assert_envelope(body, where):
    """信封四字段齐全，且必须是 JSON 对象而不是 Spring 默认错误页。"""
    assert isinstance(body, dict), f"{where} 返回的不是 JSON 对象：{body!r}"
    assert set(body) == {"code", "message", "data", "timestamp"}, f"{where} 字段集不对：{sorted(body)}"
    assert isinstance(body["code"], int), f"{where} code 不是整数"
    assert isinstance(body["message"], str), f"{where} message 不是字符串"
    assert "data" in body, f"{where} 缺 data（哪怕是 null 也必须出现）"
    assert isinstance(body["timestamp"], int), f"{where} timestamp 不是整数"


def test_route_table_covers_all_28():
    """清单本身要正好 28 条，防止以后加路由忘了补测试。"""
    ids = (
        [row[0] for row in PENDING_ROUTES]
        + [row[0] for row in IMPLEMENTED_ROUTES]
        + [UPLOAD_ROUTE[0]]
        + [STREAM_ROUTE[0]]
    )
    assert len(ids) == 28, f"应有 28 条，实际 {len(ids)}"
    assert len(set(ids)) == 28, "operationId 有重复"


@pytest.mark.parametrize(
    "operation_id,method,path,body", PENDING_ROUTES, ids=[r[0] for r in PENDING_ROUTES]
)
def test_unimplemented_route_returns_envelope_50101(java_client, operation_id, method, path, body):
    """未实现路由：HTTP 501 + code 50101 + 完整信封。"""
    resp = _call(java_client, method, path, body)
    payload = resp.json()
    _assert_envelope(payload, f"{method} {path}")
    assert resp.status_code == 501, f"{operation_id} 期望 501，实际 {resp.status_code}：{resp.text}"
    assert payload["code"] == 50101, f"{operation_id} 期望 code 50101，实际 {payload['code']}"
    assert payload["data"] is None, f"{operation_id} 未实现时 data 必须是 null"


@pytest.mark.parametrize(
    "operation_id,method,path,body", IMPLEMENTED_ROUTES, ids=[r[0] for r in IMPLEMENTED_ROUTES]
)
def test_implemented_route_returns_envelope(java_client, operation_id, method, path, body):
    """已实现路由：不管成功还是业务错误，都必须回标准信封。

    用 999999 这类不存在的 id 是刻意的：既覆盖「404 也是信封」这条，又不会污染测试库。
    """
    resp = _call(java_client, method, path, body)
    payload = resp.json()
    _assert_envelope(payload, f"{method} {path}")
    assert payload["code"] != 50101, f"{operation_id} 已实现，不该再回 50101：{resp.text}"


def test_upload_documents_returns_envelope(java_client):
    """multipart 上传接口：J2 起真落库，但信封形状必须保持。"""
    files = [("files", ("sample_ok.md", b"# hello\n\n\xe6\xad\xa3\xe6\x96\x87\n", "text/markdown"))]
    resp = java_client.post("/api/v1/documents", files=files)

    payload = resp.json()
    _assert_envelope(payload, "POST /api/v1/documents")
    assert resp.status_code == 200, resp.text
    assert payload["code"] == 0, resp.text
    assert set(payload["data"]) == {"accepted", "skipped"}, payload["data"]


def test_stream_route_rejects_invalid_body_with_envelope(java_client):
    """SSE 端点成功时回事件流；但**校验失败**必须回信封，且不能已经把响应头锁成事件流。

    这条守住的是 `ChatController` 里「先 prepare 再 new SseEmitter」的顺序：一旦反过来，
    400 就发不出来了，前端拿到的是空流 + 200，错误信息全丢。
    """
    status, content_type, events, text = read_sse({"question": ""})

    assert status == 400, f"空问题应 400，实际 {status}：{text[:400]}"
    assert not content_type.startswith("text/event-stream"), f"校验失败不该是事件流：{content_type}"
    assert not events, "校验失败不该有 SSE 事件"
    payload = json.loads(text)
    _assert_envelope(payload, "POST /api/v1/chat/stream")
    assert payload["code"] == 40001, payload


def test_unknown_path_still_returns_envelope(java_client):
    """不存在的路径也要走统一出口，不许漏出 Spring 默认白页。"""
    resp = java_client.get("/api/v1/definitely-not-a-route")

    assert resp.status_code >= 400, resp.text
    payload = resp.json()
    _assert_envelope(payload, "GET /api/v1/definitely-not-a-route")
    assert payload["code"] in (404, 40407, 50000), payload
