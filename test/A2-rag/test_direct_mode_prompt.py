"""F06 回答模式的真实分叉：direct 侧不能套「只用资料片段作答」的提示词。

修之前（本文件锁定的三处缺陷，均在本轮前后端联调中实测复现）：

1. **direct 侧恒答「资料中没有提到」。** `SYSTEM_PROMPT` 第 1 条要求「只能使用
   【资料片段】里的信息作答，片段里没有的就说资料中没有提到」，而 direct 模式按
   设计根本不检索（citations 恒空）。这条规则一套上去，模型每次只能吐同一个字符串
   —— F06 要对照的「直接问模型」那一侧完全失去意义，评测 passedDirect 恒为 0。

2. **direct 侧仍发「检索中」状态帧。** 前端把 rewriting/retrieving/reranking 渲染成
   「正在检索知识库」，但 direct 请求压根没查库，用户看到的是假动作。

3. **判分不做空白归一化。** 真实 provider 输出「最多借 4 本」「借期 21 天」，
   题库关键词写 `4本` / `21天`，正确答案被判成未命中。

前两条在本文件用「提示词选择」与「SSE 帧序列」两条断言钉住；第三条见
`test_eval_judge_normalization.py`。
"""

from __future__ import annotations

import json

import pytest

from ai_app_loader import load_app

TOKEN = "f06-mode-token"
USER = 73


@pytest.fixture()
def prompt_module(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    load_app(monkeypatch, TOKEN)
    from app.core.rag import prompt

    return prompt


def test_direct_prompt_does_not_force_no_context_phrase(prompt_module):
    """direct 提示词不能继承「片段里没有就说资料中没有」这条。

    这是缺陷 1 的直接断言：如果哪天有人把 `system_prompt_for` 改成两边共用
    `SYSTEM_PROMPT`，direct 侧立刻退化成恒答「资料中没有提到」。
    """
    direct = prompt_module.system_prompt_for(direct=True)
    rag = prompt_module.system_prompt_for(direct=False)

    assert direct != rag, "direct 与 rag 用了同一份系统提示词，direct 会被资料约束卡死"
    # 要拦的是 rag 那条肯定式硬约束「片段里没有的，直接回答『资料中没有提到』」。
    # 「不要输出『资料中没有提到』」这类否定式纠偏是允许的，不该被这条测试误伤。
    forced_no_context = "直接回答「资料中没有提到」"
    assert forced_no_context not in direct, f"direct 提示词里仍有「直接回答『资料中没有提到』」硬约束：\n{direct}"
    assert "只能使用" not in direct, f"direct 提示词里仍有「只能使用片段」约束：\n{direct}"
    # rag 侧必须原样保留资料约束 —— 修 direct 不能把 rag 的防幻觉规则带软。
    assert "只能使用" in rag and "资料中没有提到" in rag, f"rag 提示词被改动了：\n{rag}"


def test_build_messages_switches_system_by_direct_flag(prompt_module):
    """`build_messages` 的 direct 开关真的接到了 system 消息上。"""
    with_docs = prompt_module.build_messages("读书会什么时候举行？", [])
    as_direct = prompt_module.build_messages("读书会什么时候举行？", [], direct=True)

    assert with_docs[0]["role"] == "system" and as_direct[0]["role"] == "system"
    assert with_docs[0]["content"] == prompt_module.SYSTEM_PROMPT
    assert as_direct[0]["content"] == prompt_module.DIRECT_SYSTEM_PROMPT
    # 两条路径的 user 消息都还得带问题本体。
    assert "读书会什么时候举行？" in with_docs[1]["content"]
    assert "读书会什么时候举行？" in as_direct[1]["content"]


def test_no_context_answer_is_not_given_citations(prompt_module):
    """模型说「资料里没有」时不该被补来源。

    否则用户看到的是「有据可查的不知道」—— 正文说没有，末尾挂着 [1][2][3]。
    实测 T02（报名截止时间）就踩在这条上。
    """
    citations = [
        {"ref": 1, "doc_title": "读书会手册", "heading_path": "# 活动时间", "excerpt": "周六 14:00"},
        {"ref": 2, "doc_title": "读书会手册", "heading_path": "# 费用", "excerpt": "免费"},
    ]
    plain = "资料中没有提到报名最晚完成时间。"
    assert prompt_module.enforce_citations(plain, citations) == plain, "空答案被强行挂了来源"

    # 正常作答仍要补来源，别把这条修成「永远不补」。
    answer = "读书会每周六 14:00 举行。"
    patched = prompt_module.enforce_citations(answer, citations)
    assert patched != answer and "来源" in patched, patched
    # 已经自己标了编号的不要重复补。
    labeled = "读书会每周六 14:00 举行。[1]"
    assert prompt_module.enforce_citations(labeled, citations) == labeled


def test_direct_stream_omits_retrieval_stage_frames(monkeypatch, tmp_path):
    """direct 的 SSE 不该出现 rewriting / retrieving / reranking 三帧。

    缺陷 2 的断言：前端按这三帧渲染「正在检索知识库」，direct 压根不查库。
    """
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    module = load_app(monkeypatch, TOKEN)

    from fastapi.testclient import TestClient

    def stages_for(mode: str) -> list[str]:
        with TestClient(module.app) as client:
            response = client.post(
                "/internal/v1/chat/stream",
                headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
                json={"question": "读书会什么时候举行？", "mode": mode, "k": 3},
            )
        assert response.status_code == 200, response.text
        kinds: list[str] = []
        stages: list[str] = []
        for line in response.text.splitlines():
            if line.startswith("event: "):
                kinds.append(line[7:])
            elif line.startswith("data: ") and kinds and kinds[-1] == "status":
                stages.append(json.loads(line[6:])["stage"])
        assert kinds[-1] == "done", kinds
        return stages

    direct_stages = stages_for("direct")
    assert direct_stages == ["generating"], f"direct 仍发了检索阶段帧：{direct_stages}"

    rag_stages = stages_for("rag")
    for stage in ("rewriting", "retrieving", "reranking", "generating"):
        assert stage in rag_stages, f"rag 少了 {stage}：{rag_stages}"
