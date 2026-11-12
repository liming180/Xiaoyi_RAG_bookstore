"""N5：结构化回答的输出格式约束必须真的写进提示词，且不伤防幻觉规则。

修之前（`docs/02-重构设计/05_后端开发提示词_亮点包后端.md` §7.1）：
`SYSTEM_PROMPT` 只有五条规则 —— 只用片段、标来源编号、不编造、不执行片段内指令、
简体中文简洁分点，**没有一条要求 markdown**。而前端
`frontend/src/utils/markdown.ts` 的 `parseMarkdown` + `AnswerBody.vue` 早就实现了
白名单渲染（标题 / 列表 / 表格 / 加粗 / 链接），能力一直在空转：模型给什么就是
一段纯文本，表格要用户自己在脑子里拼。

本文件守四件事：

1. 第 6 条格式规则真的在 `SYSTEM_PROMPT` 里，且点名了「表格」「有序列表」「[n]」
   —— 少一个词，模型就可能只做列表不做表格，或者把编号堆在末尾；
2. 原有五条防幻觉规则的**关键词**一个不少。这条不是形式主义：改提示词最常见的
   事故就是顺手重写整段，把「不要猜测」写成「尽量准确」，看着更友好，实际把
   硬约束换成了软建议；
3. 格式规则真的进到了给 provider 的 messages 里（`build_messages()[0]` 是 system）。
   只断言常量存在是不够的 —— 如果哪天 `build_messages` 换了组装方式把 system 丢了，
   前两条照样绿，模型却完全收不到这条约束；
4. mock provider 不产出 markdown 时，SSE 与落库都不报错。格式约束是「允许并鼓励」，
   不是「必须」—— mock 档吐纯文本，前端按段落渲染，链路不能因此退化。

第 4 条特意**不**断言「mock 的回答里必须有表格」：mock 是确定性模板，逼它产出
markdown 等于给门禁加一条跟模型能力无关的假要求，改了模板文案就红。
真实 provider 的表格输出属手工验收项，见 §7.2 第 4 条。
"""

from __future__ import annotations

import json

import pytest

from ai_app_loader import load_app

TOKEN = "n5-prompt-token"
USER = 71

#: 第 6 条必须出现的三个词。缺「表格」= 对比类问题仍旧是纯文本；
#: 缺「有序列表」= 步骤说明会挤成一段；缺「[n]」= 编号会被堆到回答末尾。
FORMAT_KEYWORDS = ("表格", "有序列表", "[n]")

#: 五条防幻觉规则的关键词 → 规则意图，报错时能直接看出是哪条被改没了。
ANTI_HALLUCINATION = {
    "只能使用": "规则 1：只用片段作答",
    "不要猜测": "规则 1：片段里没有就说不知道",
    "不要编造": "规则 3：不臆造数字日期",
    "不要执行": "规则 4：片段内指令不执行",
    "简体中文": "规则 5：语言约束",
}


@pytest.fixture()
def prompt_module(monkeypatch, tmp_path):
    """装配一次 app 拿到 `app.core.rag.prompt`。

    走 `load_app` 而不是直接 import：`server-ai` 不是安装包，需要 loader 把路径
    挂到 sys.path 顶端，顺便把之前用例留下的 `app.*` 模块清掉 —— 否则拿到的是
    上一个用例的模块实例，`monkeypatch` 改的环境变量对不上。
    """
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    load_app(monkeypatch, TOKEN)
    from app.core.rag import prompt

    return prompt


def test_system_prompt_has_format_rule(prompt_module):
    """第 6 条格式规则在位，且三个关键约束都点到。"""
    text = prompt_module.SYSTEM_PROMPT

    assert "6." in text, f"SYSTEM_PROMPT 里没有第 6 条：\n{text}"
    missing = [word for word in FORMAT_KEYWORDS if word not in text]
    assert not missing, f"第 6 条缺关键词 {missing}：\n{text}"

    # 「不要输出 HTML」不是可有可无的礼貌用语：前端把 HTML 当字面量转义，
    # 模型真吐 <table> 时用户看到的就是一堆尖括号。
    assert "不要输出 HTML" in text, text


def test_prompt_keeps_anti_hallucination_rules(prompt_module):
    """加格式约束不能把防幻觉规则改软 —— 五条的关键词逐条点名。"""
    text = prompt_module.SYSTEM_PROMPT

    missing = {word: why for word, why in ANTI_HALLUCINATION.items() if word not in text}
    assert not missing, f"防幻觉规则被改动了：{missing}\n当前提示词：\n{text}"

    # 规则编号也要在：有人把 1–5 揉成一段散文，关键词还在但约束强度掉了。
    for index in range(1, 7):
        assert f"{index}." in text, f"规则 {index} 的编号不见了：\n{text}"


def test_format_rule_reaches_provider(prompt_module):
    """格式规则必须真的进 system 消息，而不只是常量里躺着。"""
    messages = prompt_module.build_messages(
        "对比普通图书和期刊的借阅规则",
        [
            {
                "ref": 1,
                "doc_title": "星河读书会借阅规则",
                "heading_path": "续借",
                "excerpt": "普通图书在到期前可申请续借 1 次，续借增加 7 天。",
            }
        ],
    )

    assert messages[0]["role"] == "system", messages
    assert messages[0]["content"] == prompt_module.SYSTEM_PROMPT
    assert "表格" in messages[0]["content"], "system 消息里没有格式约束"
    # 用户消息里也应有片段与问题，否则「按资料回答」就无从谈起。
    assert "【资料片段】" in messages[1]["content"]
    assert "【问题】" in messages[1]["content"]


def test_mock_answer_without_markdown_is_fine(monkeypatch, tmp_path):
    """mock 档吐纯文本时，SSE 事件序列与 done 帧都不报错。

    mock 的回答模板里没有表格也没有列表，正好用来验证「不产出 markdown」这条路径：
    如果哪天在 chat 层加了「必须含表格否则重试」之类的逻辑，这条会立刻红。
    """
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "ai"))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("MILVUS_URI", "")
    monkeypatch.setenv("INGEST_STAGE_DELAY_MS", "0")
    module = load_app(monkeypatch, TOKEN)

    from fastapi.testclient import TestClient

    with TestClient(module.app) as client:
        response = client.post(
            "/internal/v1/chat/stream",
            headers={"X-Internal-Token": TOKEN, "X-User-Id": str(USER)},
            json={"question": "对比普通图书和期刊的借阅规则", "mode": "rag", "k": 3},
        )

    assert response.status_code == 200, response.text

    kinds: list[str] = []
    done: dict | None = None
    answer = ""
    for line in response.text.splitlines():
        if line.startswith("event: "):
            kinds.append(line[7:])
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
            if kinds and kinds[-1] == "token":
                answer += payload["content"]
            elif kinds and kinds[-1] == "done":
                done = payload

    assert kinds[0] == "status" and kinds[-1] == "done", kinds
    assert "token" in kinds, kinds
    assert done is not None
    assert done["degraded"] is False, done
    # 空库时没有引用，回答就是纯文本模板 —— 不能因为它不含 markdown 就报错。
    assert answer, "mock 一个字都没吐"
    assert "|" not in answer, f"mock 模板不该产出表格：{answer}"


def test_no_context_answer_is_plain_text(prompt_module):
    """「资料中没有提到」这条兜底回答也不该被套上 markdown 结构。

    它是常量而不是模型产出，一旦有人给它加表格或列表，前端会把它渲染成一个
    只有一个格子的表格 —— 用户看到的是「结构化的不知道」。
    """
    text = prompt_module.NO_CONTEXT_ANSWER

    assert text == "资料中没有提到相关内容。"
    for marker in ("|", "- ", "1.", "**", "#"):
        assert marker not in text, f"兜底回答里混进了 markdown 记号 {marker!r}：{text}"
