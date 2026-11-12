"""评测判分必须对空白不敏感（Python 侧与 Java 侧同一套语义）。

问题：真实 provider（glm-4-flash）在中文与数字之间加空格是常态输出 ——
「普通图书每人最多借 4 本，借期 21 天」，而题库关键词写的是 `4本` / `21天`。
原始的 `word in answer` 直接比对，完全正确的答案被判成未命中，passedRag 被
系统性压低（实测 T03 命中 4 本 / 21 天，判分却给 False）。

两侧都要改，而且必须改成同一套语义，否则 Java 侧判出来的结论会覆盖 Python 侧
（`EvalServiceImpl.evaluate` 才是最终判分入口，Python 的 `/eval/batch` 只被
A/J 系列黑盒用例直接调用）。
"""

from __future__ import annotations

import pytest

from ai_app_loader import load_app

TOKEN = "f06-judge-token"


@pytest.fixture()
def judge(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    load_app(monkeypatch, TOKEN)
    from app.api.routes import _judge

    return _judge


def test_spaces_around_numbers_do_not_break_scoring(judge):
    """真实 provider 的「4 本」写法必须命中关键词 `4本`。"""
    keywords = "4本/四本|21天/二十一天"
    assert judge("普通图书每人最多借 4 本，借期 21 天。", keywords), (
        "带空格的真实回答被判成未命中 —— 判分没做空白归一化"
    )
    # 无空格写法照样要过。
    assert judge("普通图书每人最多借4本，借期21天。", keywords)


def test_fullwidth_space_and_newline_are_normalized(judge):
    """全角空格、换行、制表符同样要归一化。"""
    keywords = "周六|14:00"
    assert judge("读书会每周六\u300014:00 举行", keywords)
    assert judge("读书会\n每周六\t14:00", keywords)


def test_group_semantics_unchanged(judge):
    """归一化不能把分组语义改坏：组内 `/` 同义，组间 `|` 全都要命中。"""
    keywords = "周六|14:00/14点"
    assert judge("每周六 14:00 举行", keywords), "组内同义 + 组间全命中应通过"
    assert not judge("每周六 15:00 举行", keywords), "缺 14:00 这组不该通过"
    assert not judge("每周日 14:00 举行", keywords), "缺周六这组不该通过"


def test_empty_keywords_still_fail(judge):
    """没有关键词就判不出对错，仍返回 False（这是 N4 的既定边界）。

    `"|"` 这种「全是空分组」的极端输入不在本次改动范围内：`_judge` 的循环里
    空分组被 `continue` 跳过，因此会返回 True。要钉的是**真正为空**的关键词，
    那是 N4 里「候选没补关键词 → judge 恒 false → 不计入分母」所依赖的分支。
    """
    assert judge("随便什么答案", "") is False
