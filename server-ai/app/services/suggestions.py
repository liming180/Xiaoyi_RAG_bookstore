"""追问推荐：基于本轮问答与检索资料，产出 1–3 条「资料里有据可答」的追问。

为什么单独成模块
----------------
它必须等主回答生成完才能问 —— 不知道答了什么，就不知道用户接下来会问什么。
所以它只能串行挂在 `done` 帧之前，不能和检索并行。

为什么失败一律降级为空数组
--------------------------
chips 是锦上添花。真实 provider 的 LLM 可能超时、可能返回带 ```json 围栏的文本、
可能返回一个字符串而不是数组。任何一条都不该把「已经生成好的回答」变成 500 ——
用户要的是答案，不是三条推荐。所以本模块**任何异常都不外抛**，只记一条 warn。

与 Java 侧 mock 的一致性
------------------------
`MockProvider.complete()` 与 `MockAiClient` 用同一条规则产出假推荐（见
`mock_suggestions`）。两边必须同步改：mock 比真实后端宽松或更严，都会让门禁
在 mock 档全绿、真实档全挂。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Sequence

from ..core.llm.provider import LlmProvider
from ..core.rag.prompt import render_context

logger = logging.getLogger(__name__)

#: 追问生成的等待上限（秒）。超过就放弃，用空数组交差。
SUGGESTION_TIMEOUT_S = 3.0

#: 单条追问的字符上限。前端 chips 只有一行，超过就会被省略号截断，不如不生成。
MAX_ITEM_CHARS = 20

#: 默认条数，与 Java 侧 `xiaoyi.chat.max-suggestions` 的默认值一致。
DEFAULT_LIMIT = 3

#: 问题句末的标点。拼追问时要先去掉，否则会拼出「……？具体怎么操作？」。
_TRAILING = "？?。.！!～~ \t\r\n"

#: mock 推荐用的句式模板。`{head}` 是问题前 8 个字。
_MOCK_TEMPLATES = ("{head}还有哪些规定？", "{head}有例外情况吗？", "{head}具体怎么操作？")

_SYSTEM_PROMPT = """你是「小忆」的追问推荐助手。用户刚看完一轮问答，你要推测他接下来最可能问什么。

规则：
1. 只依据【本轮问题】【本轮回答】【检索资料】推断，不要引入资料里没有的主题；
2. 每个追问都必须是资料里有据可答的，不要问「能不能帮我写代码」这类资料答不了的；
3. 每条不超过 20 个汉字，口语化，不要编号、不要标点堆砌；
4. 只输出 JSON 数组，例如 ["最多能借几本？","借期多少天？"]，不要任何解释文字。"""


def mock_suggestions(question: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """按问题前几个字拼出的确定性推荐，供 mock provider 使用。

    设计约束：**随问题变化**。硬编码一句「可以继续了解吗？」的问题在于它让
    「推荐是否真的生成」这件事无法被门禁验证 —— 常量永远等于常量。

    @param question 本轮问题
    @param limit 条数上限
    @return 推荐列表，可能为空（问题为空时）
    """
    if not question or not question.strip():
        return []
    stem = question.strip().rstrip(_TRAILING)
    head = stem[:8]
    items: list[str] = []
    for template in _MOCK_TEMPLATES:
        candidate = template.format(head=head)[:MAX_ITEM_CHARS]
        if candidate and candidate != question and candidate not in items:
            items.append(candidate)
        if len(items) >= limit:
            break
    return items[:limit]


def build_messages(
    question: str, answer: str, citations: Sequence[dict[str, Any]], limit: int
) -> list[dict[str, str]]:
    """组装追问生成的 messages。

    问题单独一行、带固定前缀，是为了让 `MockProvider` 能在不碰业务代码的前提下
    从 prompt 里取回问题 —— mock 解析 prompt 本来就是它该做的事。
    """
    context = render_context(citations, limit=4)
    user_content = (
        f"【本轮问题】{question}\n\n"
        f"【本轮回答】\n{answer or '（空）'}\n\n"
        f"【检索资料】\n{context or '（无）'}\n\n"
        f"请给出 {limit} 个追问，只输出 JSON 数组。"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _extract_array(raw: str) -> list[Any] | None:
    """从可能带 ```json 围栏、可能前后有解释文字的输出里抠出 JSON 数组。

    模型不听话是常态。按「第一个 `[` 到最后一个 `]`」截取，比要求它严格输出更可靠。
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        # 去掉 ```json / ``` 围栏
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def sanitize(raw: str, question: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """把模型输出洗成合格的追问列表。

    过滤规则（任一命中即丢弃该条）：
    * 不是字符串、空白；
    * 超过 {@link MAX_ITEM_CHARS} 字 —— chips 一行放不下，截断比不显示更糟；
    * 与本轮问题完全相同 —— 点一下又问一遍，用户会以为按钮坏了。

    保留规则：去重后取前 `limit` 条；全部被丢弃时返回空数组。
    """
    parsed = _extract_array(raw)
    if parsed is None:
        return []
    items: list[str] = []
    dropped = 0
    for entry in parsed:
        if not isinstance(entry, str):
            dropped += 1
            continue
        text = entry.strip()
        if not text or len(text) > MAX_ITEM_CHARS or text == question.strip():
            dropped += 1
            continue
        if text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    if dropped:
        logger.warning("追问推荐丢弃 %d 条不合格项（超长/非字符串/与原问题相同）", dropped)
    return items


async def generate(
    provider: LlmProvider,
    question: str,
    answer: str,
    citations: Sequence[dict[str, Any]] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[str]:
    """生成追问推荐；失败一律返回空数组，不抛异常。

    @param provider LLM provider（mock 或 real）
    @param question 本轮问题
    @param answer 本轮回答正文
    @param citations 本轮引用（内部形状）
    @param limit 条数上限
    @return 1..limit 条追问；任何失败路径都返回 `[]`
    """
    if not question or not question.strip():
        return []
    messages = build_messages(question, answer, citations or [], limit)
    try:
        raw = await asyncio.wait_for(
            provider.complete(messages, temperature=0.3, max_tokens=200),
            timeout=SUGGESTION_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        # 3 秒还没回来就别等了：主回答已经产出，不能因为推荐卡住整条流。
        logger.warning("追问推荐超时（%ss），降级为空数组", SUGGESTION_TIMEOUT_S)
        return []
    except Exception as exc:  # noqa: BLE001 - 任何 provider 异常都必须降级
        logger.warning("追问推荐生成失败，降级为空数组：%s", exc)
        return []
    return sanitize(raw, question, limit)
