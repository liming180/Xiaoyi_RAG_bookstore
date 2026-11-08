"""N2 Python 侧：追问推荐必须真生成、随问题变化、任何失败都不外抛。

这一层守的是 `server-ai/app/services/suggestions.py` 的契约：

1. `generate()` 用 provider 的**一次性**补全（不是流式），因为要等完整 JSON 才能解析；
2. 超时 / 抛异常 / 返回非数组 / 条目超长 → 一律空数组，**不抛异常**；
3. mock provider 的产出随问题变化（否则「真生成」这条断言没有说服力）；
4. `done.suggestions` 与主回答串行：回答完才问，且失败不改变本帧其它字段。

为什么要单独测 `sanitize()`
---------------------------
真实 LLM 的输出长什么样是概率问题：带 ```json 围栏、前后夹解释文字、
返回字符串而不是数组、返回 25 个字的超长句。这些都能只用纯函数喂进去验，
不必每个都起一次服务。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from ai_app_loader import load_app

TOKEN = "n2-suggestions-token"
USER = 51


@pytest.fixture()
def module(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    return load_app(monkeypatch, TOKEN)


@pytest.fixture()
def client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


def _events(text: str) -> list[tuple[str | None, dict]]:
    events: list[tuple[str | None, dict]] = []
    current = None
    for line in text.splitlines():
        if line.startswith("event: "):
            current = line[7:]
        elif line.startswith("data: "):
            events.append((current, json.loads(line[6:])))
    return events


def _ask(client, question: str, mode: str = "rag") -> dict:
    response = client.post(
        "/internal/v1/chat/stream",
        headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
        json={"question": question, "history": [], "mode": mode, "k": 3},
    )
    assert response.status_code == 200, response.text
    done = [data for kind, data in _events(response.text) if kind == "done"]
    assert done, response.text
    return done[0]


def test_done_frame_has_generated_suggestions(client) -> None:
    """done.suggestions 是 1..3 条非空字符串，且每条不超过 20 字。"""
    done = _ask(client, "普通图书最多借几本，借期多久？")
    items = done["suggestions"]

    assert isinstance(items, list), done
    assert 1 <= len(items) <= 3, items
    for item in items:
        assert isinstance(item, str) and item.strip(), item
        assert len(item) <= 20, f"超过 20 字：{item!r}"
    assert len(set(items)) == len(items), f"有重复：{items}"


def test_suggestions_vary_with_question(client) -> None:
    """两个不同问题的推荐不能相同 —— 旧实现硬编码一句，这条会失败。"""
    first = _ask(client, "普通图书最多借几本？")["suggestions"]
    second = _ask(client, "讨论空间怎么预约？")["suggestions"]

    assert first and second
    assert set(first) != set(second), f"推荐是常量：{first} == {second}"


def test_direct_mode_returns_empty_suggestions(client) -> None:
    """direct 不检索，没有「资料里有据可答」的追问，返回空数组而不是编造。"""
    done = _ask(client, "普通图书最多借几本？", mode="direct")
    assert done["suggestions"] == [], done["suggestions"]


def test_sanitize_accepts_fenced_json(module) -> None:
    """模型常把 JSON 包在 ```json 围栏里，必须能抠出来。"""
    from app.services.suggestions import sanitize

    raw = '```json\n["最多几本？","借期多少天？"]\n```'
    assert sanitize(raw, "借阅规则") == ["最多几本？", "借期多少天？"]


def test_sanitize_keeps_json_among_explanations(module) -> None:
    """前后夹一段解释文字时，按第一个 `[` 到最后一个 `]` 截取。"""
    from app.services.suggestions import sanitize

    raw = '好的，以下是推荐：["能续借吗？"] 希望对你有帮助。'
    assert sanitize(raw, "借阅规则") == ["能续借吗？"]


def test_sanitize_drops_long_items(module) -> None:
    """超过 20 字的条目直接丢弃：chips 一行放不下，截断比不显示更糟。"""
    from app.services.suggestions import MAX_ITEM_CHARS, sanitize

    too_long = "这个问题非常非常长" * 4
    assert len(too_long) > MAX_ITEM_CHARS
    assert sanitize(json.dumps(["能续借吗？", too_long]), "借阅规则") == ["能续借吗？"]


def test_sanitize_drops_item_equal_to_question(module) -> None:
    """与本轮问题完全相同的推荐要丢掉：点一下又问一遍，用户会以为按钮坏了。"""
    from app.services.suggestions import sanitize

    question = "普通图书最多借几本？"
    assert sanitize(json.dumps([question, "借期多少天？"]), question) == ["借期多少天？"]


def test_sanitize_rejects_non_array_and_garbage(module) -> None:
    """返回字符串 / 对象 / 空串 / 坏 JSON 都回空数组，不抛异常。"""
    from app.services.suggestions import sanitize

    for raw in ('"最多几本？"', '{"a":1}', "", "not json at all", "[]"):
        assert sanitize(raw, "问题") == [], raw


def test_generate_degrades_on_provider_exception(module) -> None:
    """provider 抛异常时 generate 返回空数组，不把异常传给 SSE 层。"""
    from app.services.suggestions import generate

    class Boom:
        async def complete(self, messages, temperature=0.3, max_tokens=200):
            raise RuntimeError("LLM 不可达")

    result = asyncio.run(generate(Boom(), "问题", "回答", []))
    assert result == []


def test_generate_degrades_on_timeout(module, monkeypatch) -> None:
    """provider 迟迟不返回时按超时降级，不卡住整条流。"""
    from app.services import suggestions

    class Slow:
        async def complete(self, messages, temperature=0.3, max_tokens=200):
            await asyncio.sleep(5)
            return '["不该等到这一条"]'

    monkeypatch.setattr(suggestions, "SUGGESTION_TIMEOUT_S", 0.05)
    result = asyncio.run(suggestions.generate(Slow(), "问题", "回答", []))
    assert result == []


def test_generate_returns_empty_for_blank_question(module) -> None:
    """空问题不调用 provider（省一次 LLM 调用），直接空数组。"""
    from app.services import suggestions

    calls: list[object] = []

    class Recorder:
        async def complete(self, messages, temperature=0.3, max_tokens=200):
            calls.append(messages)
            return '["不该出现"]'

    assert asyncio.run(suggestions.generate(Recorder(), "   ", "回答", [])) == []
    assert calls == []


def test_abstract_provider_fails_loudly(module) -> None:
    """没实现 complete() 的 provider 要立刻炸，而不是静默返回空串。

    静默返回空串会让「推荐没生成」看起来像「模型没话说」，是更难查的 bug。
    """
    from app.core.llm.provider import LlmProvider

    class Bare(LlmProvider):
        async def answer(self, question, citations=None):
            yield ""

        def usage(self, question, answer):
            return {"prompt_tokens": 0, "completion_tokens": 0}

    provider = Bare()
    with pytest.raises(NotImplementedError):
        asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))


def test_real_provider_unreachable_degrades_to_empty(module) -> None:
    """真实 provider 档：LLM 端点不可达时 done 仍正常、suggestions 是 []。

    这条对应提示词 §4.2 测试第 3 条。这里不打真的公网 —— 把 endpoint 指到本机一个
    没人监听的端口，连接立刻被拒，等价于「LLM 不可达」，但不用等 60 秒超时。
    """
    from app.config import Settings
    from app.core.llm.provider import OpenAiProvider
    from app.services import suggestions

    settings = Settings(
        internal_token=TOKEN,
        ai_provider="real",
        llm_endpoint="http://127.0.0.1:9",  # RFC 6335 discard 端口，本机不会有服务
        llm_model="glm-4-flash",
        llm_timeout_ms=2000,
        embedding_endpoint="http://127.0.0.1:9",
        embedding_model="embedding-3",
    )
    provider = OpenAiProvider(settings)

    # provider 自己会抛（连接被拒），这是对的 —— 上层必须靠这个异常判断失败
    with pytest.raises(Exception):
        asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))

    # 但 generate() 必须把它吃掉，返回空数组
    result = asyncio.run(suggestions.generate(provider, "普通图书最多借几本？", "4 本。", []))
    assert result == [], result
