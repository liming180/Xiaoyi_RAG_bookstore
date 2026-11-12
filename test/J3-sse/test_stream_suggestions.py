"""N2：追问推荐必须真生成、能落库、能回放。

背景（`docs/02-重构设计/RAG文档.md` §5 在线管线的追问推荐）：
`server-ai/app/services/chat.py` 硬编码 `"suggestions": ["可以继续了解吗？"]`，
每个问题都回同一句；`ConversationServiceImpl.toVO` 恒给 `List.of()`，
`Message` 实体也没有 suggestions 列 —— 刷新页面 chips 全丢。

本文件守三件事：

1. `done.suggestions` **随问题变化**（常量永远等于常量，等于没生成）；
2. 历史消息回放**仍带 chips**（这是落库那一半的验收点）；
3. 降级与空问题**不编造推荐**，也不让主流程失败。

为什么「随问题变化」这条不能省
------------------------------
只断言「长度 1..3 且都是字符串」的话，硬编码那一句旧实现**照样通过**。
把两组不同问题拿来做集合差集，才是「真生成」的判据。
"""

from __future__ import annotations

import json

import pytest

from conftest import read_sse, wait_until

pytestmark = pytest.mark.live

#: 单条追问的字符上限，与 `server-ai/app/services/suggestions.py` 的 MAX_ITEM_CHARS 一致。
MAX_ITEM_CHARS = 20

#: 契约 done.suggestions 的展示位上限（Java `xiaoyi.chat.max-suggestions` 默认 3）。
MAX_SUGGESTIONS = 3


def _make_conversation(java_client, title: str) -> int:
    data = java_client.post("/api/v1/conversations", json={"title": title}).json()["data"]
    return int(data["id"])


def _ask(java_client, conversation_id: int, question: str, mode: str = "rag", k: int = 3):
    """发一次流式问答，返回 `(done 帧 data, 事件名列表)`。"""
    status, content_type, events, text = read_sse(
        {
            "conversationId": str(conversation_id),
            "question": question,
            "mode": mode,
            "k": k,
        }
    )
    assert status == 200, f"SSE 应 200，实际 {status}：{text[:400]}"
    assert content_type.startswith("text/event-stream"), content_type

    done = None
    names: list[str] = []
    for event in events:
        names.append(event.event)
        if event.event == "done":
            done = json.loads(event.data)
    assert done is not None, f"没有收到 done：{names}"
    return done, names


def test_done_suggestions_shape(java_client, clean_db):
    """done.suggestions 是 1..3 条、每条不超过 20 字、且不等于原问题。"""
    conversation_id = _make_conversation(java_client, "N2 追问形状")
    try:
        question = "普通图书最多借几本？"
        done, _names = _ask(java_client, conversation_id, question)
        items = done["suggestions"]

        assert isinstance(items, list), done
        assert 1 <= len(items) <= MAX_SUGGESTIONS, f"推荐条数应在 1..{MAX_SUGGESTIONS}：{items}"
        for item in items:
            assert isinstance(item, str), f"混入非字符串：{item!r}"
            assert item.strip(), f"出现空白项：{items}"
            assert len(item) <= MAX_ITEM_CHARS, f"单条超过 {MAX_ITEM_CHARS} 字：{item!r}"
            assert item != question, f"推荐与原问题完全相同（点了又问一遍）：{item!r}"
        assert len(set(items)) == len(items), f"推荐内有重复：{items}"
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")


def test_suggestions_differ_between_questions(java_client, clean_db):
    """两个不同问题 → 两组推荐不完全相同。这是「不是常量」的判据。

    旧实现（硬编码「可以继续了解吗？」）会让这条用例失败 —— 这正是它存在的理由。
    """
    conversation_id = _make_conversation(java_client, "N2 追问随问题变")
    try:
        first, _ = _ask(java_client, conversation_id, "普通图书最多借几本？")
        second, _ = _ask(java_client, conversation_id, "讨论空间怎么预约？")

        assert first["suggestions"], first
        assert second["suggestions"], second
        assert set(first["suggestions"]) != set(second["suggestions"]), (
            f"两个不同问题的推荐完全相同，说明推荐是常量：{first['suggestions']}"
        )
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")


def test_suggestions_persist_and_replay(java_client, clean_db):
    """刷新/切回会话后 chips 仍在：`GET /messages` 里 assistant 消息带同一份推荐。

    这条守的是落库那一半。只把推荐放进 done 帧、不写 suggestions_json，
    前端刷新就只剩一条没有 chips 的回答。
    """
    conversation_id = _make_conversation(java_client, "N2 追问回放")
    try:
        question = "续借有什么限制？"
        done, _names = _ask(java_client, conversation_id, question)
        emitted = done["suggestions"]
        assert emitted, done

        def _read():
            rows = java_client.get(f"/api/v1/conversations/{conversation_id}/messages").json()[
                "data"
            ]
            assistant = [row for row in rows if row["role"] == "assistant"]
            return assistant[0] if assistant else None

        row = wait_until(_read, timeout=15, message="done 之后 15s 内应能读到 assistant 消息")

        assert row["suggestions"] == emitted, (
            f"回放的推荐与 done 帧不一致：done={emitted} row={row['suggestions']}"
        )
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")


def test_direct_mode_has_no_suggestions(java_client, clean_db):
    """direct 模式不检索，也就没有「资料里有据可答」的追问 —— 返回空数组而不是编造。

    契约允许 0 条（`suggestions: array`，没写 minItems），前端 `SuggestionChips`
    在空数组时不渲染也不报错。
    """
    conversation_id = _make_conversation(java_client, "N2 直答无追问")
    try:
        done, names = _ask(java_client, conversation_id, "普通图书最多借几本？", mode="direct")

        assert "retrieval" not in names, f"direct 不该发 retrieval：{names}"
        assert done["suggestions"] == [], f"direct 不该编造追问：{done['suggestions']}"
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")


def test_blank_question_is_rejected_before_suggestion_generation(java_client, clean_db):
    """空问题在校验层就被 40001 挡住，不会走到「生成推荐」那一步。

    推荐生成要串行等 LLM，如果空问题能穿过去，用户会先等满 3 秒超时才拿到错误。
    """
    conversation_id = _make_conversation(java_client, "N2 空问题")
    try:
        status, content_type, events, text = read_sse(
            {"conversationId": str(conversation_id), "question": "", "mode": "rag", "k": 3}
        )
        assert status == 400, f"应 400，实际 {status}：{text[:300]}"
        assert not content_type.startswith("text/event-stream"), content_type
        assert not events, "校验失败不该有 SSE 事件"
        assert json.loads(text)["code"] == 40001, text
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")


def test_suggestions_survive_second_turn(java_client, clean_db):
    """同一会话第二轮之后，**第一轮**的推荐依然在 —— 落库是按消息行存的，不是会话级。

    如果实现把推荐存成「会话上最后一次的推荐」，这条会失败：第二轮会覆盖第一轮。
    """
    conversation_id = _make_conversation(java_client, "N2 两轮各自保留")
    try:
        first, _ = _ask(java_client, conversation_id, "普通图书最多借几本？")
        second, _ = _ask(java_client, conversation_id, "讨论空间怎么预约？")

        def _read():
            rows = java_client.get(f"/api/v1/conversations/{conversation_id}/messages").json()[
                "data"
            ]
            assistant = [row for row in rows if row["role"] == "assistant"]
            return assistant if len(assistant) >= 2 else None

        assistants = wait_until(_read, timeout=15, message="两轮之后应有两条 assistant 消息")
        assert assistants[0]["suggestions"] == first["suggestions"], (
            f"第一轮推荐被覆盖了：{assistants[0]['suggestions']} != {first['suggestions']}"
        )
        assert assistants[1]["suggestions"] == second["suggestions"], (
            f"第二轮推荐落库不对：{assistants[1]['suggestions']} != {second['suggestions']}"
        )
    finally:
        java_client.delete(f"/api/v1/conversations/{conversation_id}")
