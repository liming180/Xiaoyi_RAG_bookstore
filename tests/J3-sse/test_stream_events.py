"""J3 SSE 事件流：事件顺序、data 形状、done 帧字段。

手册 §7「测试（test/J3-sse/ 下写）」第 1 条：
`test_stream_events.py`（事件顺序 status≥3 → retrieval → token≥1 → done；data 是合法 JSON 且字段齐全）。

契约依据 `docs/api/openapi-public.yaml`：

- `:227-317` `/api/v1/chat/stream`：每帧 `data:` 是**独立 JSON，不包信封**（全契约唯一例外）；
  `x-sse-events` 声明 status「至少 3 帧」、retrieval「`mode=direct` 时省略」、token「至少 1 帧」。
- `:1539-1545 StatusEventData` required `[stage]`，`stage ∈ {rewriting, retrieving, reranking, generating}`。
- `:1547-1555 RetrievalEventData` required `[citations]`，items 是 `Citation`。
- `:1557-1563 TokenEventData` required `[content]`。
- `:1565-1592 DoneEventData` required `[messageId, usage, elapsedMs, degraded, suggestions]`。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse

pytestmark = pytest.mark.live

STAGES = {"rewriting", "retrieving", "reranking", "generating"}

DONE_KEYS = {"messageId", "usage", "elapsedMs", "degraded", "suggestions"}

CITATION_KEYS = {
    "ref",
    "chunkId",
    "docId",
    "docTitle",
    "headingPath",
    "text",
    "start",
    "end",
    "score",
    "kind",
    "verified",
}


def _make_conversation(java_client) -> int:
    """建一个干净会话，避免用例之间互相污染消息计数。"""
    data = java_client.post("/api/v1/conversations", json={"title": "SSE 用例"}).json()["data"]
    return int(data["id"])


def _ask(java_client, question: str, mode: str = "rag", k: int = 3):
    """发一次流式问答，返回 `(状态码, content-type, [(事件名, data 对象)], 原文)`。"""
    conversation_id = _make_conversation(java_client)
    payload = {
        "conversationId": str(conversation_id),
        "question": question,
        "mode": mode,
        "k": k,
    }
    status, content_type, events, text = read_sse(payload)
    decoded: list[tuple[str, object]] = []
    for event in events:
        assert event.data, f"事件 {event.event} 的 data 是空串，违反「data 是合法 JSON」"
        try:
            decoded.append((event.event, json.loads(event.data)))
        except json.JSONDecodeError as exc:  # pragma: no cover - 失败时给出可读上下文
            raise AssertionError(
                f"事件 {event.event} 的 data 不是合法 JSON：{event.data!r}（{exc}）"
            ) from exc
    return status, content_type, decoded, text


def _names(decoded: list[tuple[str, object]]) -> list[str]:
    return [name for name, _ in decoded]


def test_stream_returns_event_stream_content_type(java_client, clean_db):
    """`/chat/stream` 的响应必须是 `text/event-stream`，否则前端 SSE 解析器不会启动。"""
    status, content_type, decoded, text = _ask(java_client, "读书会几点开始？")

    assert status == 200, f"SSE 应 200，实际 {status}：{text[:400]}"
    assert content_type.startswith("text/event-stream"), f"Content-Type 不对：{content_type}"
    assert decoded, "没有收到任何事件"


def test_stream_event_order_status_retrieval_token_done(java_client, clean_db):
    """事件顺序：status≥3 → retrieval → token≥1 → done，且 done 是最后一帧。"""
    _status, _ct, decoded, _text = _ask(java_client, "读书会几点开始？")
    names = _names(decoded)

    assert names.count("status") >= 3, f"status 至少 3 帧，实际 {names.count('status')}：{names}"
    assert "retrieval" in names, f"rag 模式必须发 retrieval：{names}"
    assert names.count("token") >= 1, f"token 至少 1 帧：{names}"
    assert names[-1] == "done", f"done 必须是最后一帧：{names}"
    assert "error" not in names, f"正常路径不该出现 error：{names}"

    first_status = names.index("status")
    retrieval_at = names.index("retrieval")
    first_token = names.index("token")
    assert first_status < retrieval_at, f"retrieval 不能早于 status：{names}"
    assert retrieval_at < first_token, f"retrieval 应在 token 之前：{names}"


def test_stream_status_stage_values_are_in_enum(java_client, clean_db):
    """status 帧的 stage 只能取契约里的四个值。"""
    _status, _ct, decoded, _text = _ask(java_client, "读书会几点开始？")

    stages = [data["stage"] for name, data in decoded if name == "status"]
    assert stages, "没有 status 帧"
    for stage in stages:
        assert stage in STAGES, f"stage={stage!r} 不在 {sorted(STAGES)} 里"
    assert len(set(stages)) >= 3, f"stage 至少出现三种，实际 {stages}"


def test_stream_retrieval_citations_match_contract(java_client, clean_db):
    """retrieval 帧的 citations 每条都要满足 Citation 的 required 与取值约束。"""
    _status, _ct, decoded, _text = _ask(java_client, "普通图书最多借几本？")

    retrieval = [data for name, data in decoded if name == "retrieval"]
    assert len(retrieval) == 1, f"rag 模式应恰好一帧 retrieval，实际 {len(retrieval)}"
    citations = retrieval[0]["citations"]
    assert isinstance(citations, list) and citations, f"citations 不该为空：{citations}"

    for cite in citations:
        missing = CITATION_KEYS - set(cite)
        assert not missing, f"Citation 缺字段 {sorted(missing)}：{cite}"
        assert 0.0 <= cite["score"] <= 1.0, f"score 越界：{cite['score']}"
        assert cite["chunkId"].startswith("D"), f"chunkId 形状不对：{cite['chunkId']}"
        assert isinstance(cite["verified"], bool), f"verified 应是布尔：{cite['verified']}"


def test_stream_token_content_is_string(java_client, clean_db):
    """token 帧的 content 必须是非空字符串。"""
    _status, _ct, decoded, _text = _ask(java_client, "读书会几点开始？")

    tokens = [data["content"] for name, data in decoded if name == "token"]
    assert tokens, "没有 token 帧"
    for token in tokens:
        assert isinstance(token, str), f"token content 不是字符串：{token!r}"
        assert token, "token content 不能为空串"


def test_stream_done_frame_matches_contract(java_client, clean_db):
    """done 帧必须带齐 5 个 required 字段，且取值类型正确。"""
    _status, _ct, decoded, _text = _ask(java_client, "读书会几点开始？")

    done = [data for name, data in decoded if name == "done"]
    assert len(done) == 1, f"应恰好一帧 done，实际 {len(done)}"
    payload = done[0]

    missing = DONE_KEYS - set(payload)
    assert not missing, f"done 缺字段 {sorted(missing)}：{payload}"
    assert payload["messageId"] is not None, f"done.messageId 不能为 null：{payload}"
    assert isinstance(payload["elapsedMs"], int) and payload["elapsedMs"] >= 0, payload
    assert payload["degraded"] is False, f"正常路径 degraded 必须是 false：{payload}"
    assert isinstance(payload["suggestions"], list), payload
    for item in payload["suggestions"]:
        assert isinstance(item, str), f"suggestions 里混入非字符串：{item!r}"

    usage = payload["usage"]
    assert isinstance(usage, dict) and usage, f"usage 应是非空对象或 null，实际 {usage!r}"
    for key, value in usage.items():
        assert isinstance(value, int), f"usage.{key} 必须是整数（契约 additionalProperties: integer）"


def test_stream_direct_mode_omits_retrieval(java_client, clean_db):
    """`mode=direct` 时按契约省略 retrieval 帧。"""
    _status, _ct, decoded, _text = _ask(java_client, "读书会几点开始？", mode="direct")
    names = _names(decoded)

    assert "retrieval" not in names, f"direct 模式不该发 retrieval：{names}"
    assert names[-1] == "done", f"done 必须是最后一帧：{names}"
    assert names.count("token") >= 1, f"direct 也要有 token：{names}"


def test_stream_top_k_controls_citation_count(java_client, clean_db):
    """`k` 必须真的生效：k=1 与 k=3 的引用条数不同，否则参数等于没接。"""
    _s1, _c1, decoded_one, _t1 = _ask(java_client, "普通图书最多借几本？", k=1)
    _s3, _c3, decoded_three, _t3 = _ask(java_client, "普通图书最多借几本？", k=3)

    one = [data for name, data in decoded_one if name == "retrieval"][0]["citations"]
    three = [data for name, data in decoded_three if name == "retrieval"][0]["citations"]

    assert len(one) == 1, f"k=1 应只回 1 条引用：{one}"
    assert len(three) == 3, f"k=3 应回 3 条引用：{three}"
    assert [c["ref"] for c in three] == [1, 2, 3], f"ref 应按 1..n 重编号：{three}"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"question": "", "mode": "rag", "k": 3}, 40001),
        ({"question": "测试", "mode": "bogus", "k": 3}, 40001),
        ({"question": "测试", "mode": "rag", "k": 11}, 40001),
    ],
)
def test_stream_invalid_request_returns_envelope(java_client, clean_db, payload, expected_code):
    """校验失败要在建 emitter 之前挡住，返回 JSON 信封而不是空的 event-stream。"""
    status, content_type, events, text = read_sse(payload)

    assert status == 400, f"应 400，实际 {status}：{text[:400]}"
    assert not content_type.startswith("text/event-stream"), (
        f"校验失败不该返回事件流：{content_type}"
    )
    assert not events, "校验失败不该有 SSE 事件"
    body = json.loads(text)
    assert body["code"] == expected_code, body
    assert body["data"] is None, body
    assert set(body) == {"code", "message", "data", "timestamp"}, body


def test_stream_unknown_conversation_returns_40406(java_client, clean_db):
    """会话不存在时回 404 + 40406，同样在流开始之前。"""
    status, content_type, _events, text = read_sse(
        {"conversationId": "999999", "question": "读书会几点开始？", "mode": "rag", "k": 3}
    )

    assert status == 404, f"应 404，实际 {status}：{text[:400]}"
    assert not content_type.startswith("text/event-stream"), content_type
    assert json.loads(text)["code"] == 40406, text
