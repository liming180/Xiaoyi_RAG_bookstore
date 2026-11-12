"""F06 对照模式：both 的「直接答」侧必须真正独立生成。

修之前（本轮实测复现的致命缺陷）：

```python
if req.mode == "both":
    done["direct_content"] = answer   # answer 是 rag 侧的结果
```

后果不只是「两栏内容一样」——direct 侧还继承了 rag 侧的 `[1]` 引用标记，一个
根本没检索的模式却挂着来源编号。F06「对照」的全部意义（比较有资料 vs 无资料的
差别）被这一行抹掉了：用户在「对照」里看到的其实是同一份答案的两份拷贝。

**为什么用 spy 而不是比较文本**：mock provider 对「空引用」的两次调用会产出
逐字相同的字符串，于是「两段文本相同」既可能来自真 bug、也可能来自 mock 的正常
行为，无法区分。这里改成记录 `provider.answer` 的**调用参数**：both 模式必须
出现两次调用，且其中恰好一次 `direct=True` 且 citations 为空。这是结构性判据，
不受 mock 措辞影响。
"""

from __future__ import annotations

import json

import pytest

from ai_app_loader import load_app

TOKEN = "f06-both-token"
USER = 74


@pytest.fixture()
def app_module(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    return load_app(monkeypatch, TOKEN)


def _stream(module, question: str, mode: str, k: int = 3) -> dict:
    """跑一次 SSE，返回 {事件种类列表, 累积正文, done 帧数据}。"""
    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        response = client.post(
            "/internal/v1/chat/stream",
            headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
            json={"question": question, "mode": mode, "k": k},
        )
    assert response.status_code == 200, response.text

    kinds: list[str] = []
    text = ""
    done: dict = {}
    for line in response.text.splitlines():
        if line.startswith("event: "):
            kinds.append(line[7:])
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
            if kinds and kinds[-1] == "token":
                text += payload.get("content", "")
            elif kinds and kinds[-1] == "done":
                done = payload
    return {"kinds": kinds, "text": text, "done": done}


@pytest.fixture()
def answer_calls(monkeypatch):
    """记录 provider.answer 每次调用的 (citations 条数, direct 标志)。"""
    calls: list[tuple[int, bool]] = []
    from app.core.llm import provider as provider_module

    original = provider_module.MockProvider.answer

    def spy(self, question, citations=None, direct=False):
        calls.append((len(citations or []), direct))
        return original(self, question, citations, direct)

    monkeypatch.setattr(provider_module.MockProvider, "answer", spy)
    return calls


def test_both_mode_runs_two_independent_generations(app_module, answer_calls):
    """both 模式必须调用 provider 两次，其中恰好一次是 direct。

    这是本文件的核心断言：把代码改回 `done["direct_content"] = answer`，
    调用次数会掉到 1 次且没有 direct=True —— 这条立刻失败。
    """
    answer_calls.clear()
    _stream(app_module, "普通图书最多借几本？", "both")

    assert len(answer_calls) == 2, (
        "both 模式应该跑两次生成（rag + direct），实际调用："
        f"{answer_calls} —— 说明 direct 侧又变成了 rag 结果的拷贝"
    )
    direct_calls = [c for c in answer_calls if c[1] is True]
    assert len(direct_calls) == 1, f"应恰好有一次 direct=True 的生成，实际：{answer_calls}"
    # direct 那一侧必须不带任何引用片段 —— 它按设计不检索。
    assert direct_calls[0][0] == 0, (
        f"direct 侧被喂了引用片段（{direct_calls[0][0]} 条），说明它走了 rag 链路"
    )
    # 另一侧必须是 rag（带 direct=False）。
    rag_calls = [c for c in answer_calls if c[1] is False]
    assert len(rag_calls) == 1, f"应有恰好一次 rag 生成，实际：{answer_calls}"


def test_both_mode_direct_content_has_no_citation_markers(app_module):
    """direct 侧没有检索，就不该出现引用编号。

    修之前 direct 内容里带着 rag 的 `[1]`，是「拷贝」最直观的证据：
    一个没查库的模式不可能知道来源编号。
    """
    result = _stream(app_module, "普通图书最多借几本？", "both")
    direct = result["done"]["direct_content"]

    assert "[" not in direct, f"direct 侧出现了引用标记，说明它不是独立生成的：{direct!r}"


def test_both_mode_direct_present_and_non_empty(app_module):
    """done 帧必须带 non-empty 的 direct_content，否则前端右栏永远是空的。"""
    result = _stream(app_module, "普通图书最多借几本？", "both")
    direct = result["done"].get("direct_content")

    assert direct is not None, "both 模式下 done 帧缺少 direct_content"
    assert direct.strip(), "direct_content 是空串，前端右栏会显示空白"


def test_both_mode_direct_uses_direct_prompt_not_rag_prompt(app_module):
    """both 里的 direct 半侧不能继承 rag 的「只能用片段」约束。

    判据是行为而不是文案：rag 提示词要求「片段里没有就答资料中没有提到」，
    若 direct 侧套用了它，答案会退化成同一句无信息量的拒答。
    """
    result = _stream(app_module, "参加读书会要交多少费用？", "both")
    direct = result["done"]["direct_content"]

    forced_no_context = "资料中没有提到"
    assert forced_no_context not in direct, (
        "both 的 direct 侧退化成「资料中没有提到」，说明它套用了 rag 提示词："
        f"{direct!r}"
    )


def test_direct_only_mode_unchanged(app_module, answer_calls):
    """单独 direct 模式不能被这次修改带偏：仍只生成一次、不发 retrieval 帧。"""
    answer_calls.clear()
    result = _stream(app_module, "普通图书最多借几本？", "direct")

    assert len(answer_calls) == 1, f"direct 模式应只生成一次，实际：{answer_calls}"
    assert answer_calls[0][1] is True, f"direct 模式的生成没带 direct=True：{answer_calls}"
    assert "retrieval" not in result["kinds"], result["kinds"]
    # 单独 direct 模式不该有 direct_content（那是 both 专有字段）。
    assert "direct_content" not in result["done"], (
        "direct 模式意外带上了 direct_content，字段语义被搞混了"
    )
