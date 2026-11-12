"""全局摘要卡：把整库语料压成两张「能回答全局问题」的卡片。

为什么需要它
------------
普通片段是「按段落切的」：问「普通图书最多借几本」能命中 `02_借阅规则.md` 的某一段，
但问「整个资料库一共能借几本、借多久」这类**跨资料统计**问题时，任何单个片段都只是
部分答案。摘要卡把全库压成两张卡：

* **统计卡**（`kind=summary`）—— 面向「一共多少 / 有几份 / 覆盖哪些主题」；
* **规则卡**（`kind=rule`）—— 面向「谁有资格 / 什么条件下可以」这类资格类问题。

编号约定（写进契约，别自己发明）
--------------------------------
摘要卡不属于任何一份资料，但 `Citation.docId` 是 required。定案：**文档号 00 归摘要**，
即 `chunk_id = D00-C001 …`，`doc_id = "__summary__"`、`doc_title = "全库摘要"`。
资料编号仍从 `D01` 起，`MAX_DOCS_PER_USER = 99` 的语义不变 —— 摘要卡不参与文档号分配，
否则每建一次库就会吃掉一个资料名额。

失败策略
--------
摘要生成失败**不能让建库失败**。降级为「无摘要卡」，任务仍 SUCCEEDED，
manifest 里 `summary` 为 null。原因写进任务日志，不写 `error` 字段
（`error` 只用于任务失败）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

logger = logging.getLogger(__name__)

#: 摘要卡的文档号：00 保留给「全库」，资料从 01 起。
SUMMARY_DOC_NO = 0

#: 摘要卡在 `chunk.doc_id` 里的取值。
SUMMARY_DOC_ID = "__summary__"

#: 摘要卡的资料标题。
SUMMARY_DOC_TITLE = "全库摘要"

#: 一批里最多生成几张卡（统计卡 + 规则卡）。
MAX_CARDS = 2

#: 单张卡的正文上限，避免把整库正文塞进一个 chunk。
MAX_CARD_CHARS = 600

#: 生成摘要卡的等待上限（秒）。真实 provider 下超时就降级。
SUMMARY_TIMEOUT_S = 8.0

_SYSTEM_PROMPT = """你在为一个「个人资料助手」生成全局摘要卡。

输入是整个资料库的正文。请产出两张卡，用 JSON 数组输出：

[
  {"kind":"summary","title":"...","content":"...","sources":["<资料号>", ...]},
  {"kind":"rule","title":"...","content":"...","sources":["<资料号>", ...]}
]

规则：
1. `summary` 卡回答「一共多少 / 有几份 / 覆盖哪些主题」这类全局统计；
2. `rule` 卡回答「谁有资格 / 什么条件下可以」这类资格规则；
3. 正文不超过 300 字，只用资料里出现过的数字与条件，**不要推测**；
4. `title` 不超过 20 字；
5. 只输出 JSON 数组，不要解释文字。"""


@dataclass
class SummaryCard:
    """一张摘要卡。"""

    kind: str
    title: str
    content: str
    sources: list[str] = field(default_factory=list)


def _numeric_sentences(documents: Sequence[Any]) -> list[str]:
    """抽出含数字的句子，按「像不像借阅规则」排序。

    为什么必须排序：语料里 01 号的「14:00 至 16:00」也含数字，但那是活动时间，
    不是借阅规则。规则卡的价值全在「4 本 / 21 天」这类条款上，先挑带「借/册/本/天」
    的句子，再退回其它数字句。
    """
    sentences: list[tuple[int, str]] = []
    for doc in documents:
        text = getattr(doc, "text", "") or ""
        for raw in re.split(r"[。；;\n]+", text):
            sentence = raw.strip()
            if not sentence or not re.search(r"\d", sentence):
                continue
            weight = 1 if re.search(r"借|册|天|期限|上限", sentence) else 0
            sentences.append((weight, sentence))
    sentences.sort(key=lambda item: -item[0])
    return [sentence for _weight, sentence in sentences]


def mock_cards(documents: Sequence[Any]) -> list[SummaryCard]:
    """确定性的摘要卡，供 mock provider 与门禁使用。

    **不调用任何模型**：门禁要能在离线环境里断言「卡片存在、编号合规、规则卡含关键数字」，
    真去调一次 LLM 会让每条用例都慢 1–2 秒且结果不可复现。
    """
    if not documents:
        return []
    titles = [
        (getattr(doc, "title", "") or getattr(doc, "name", "") or str(doc.doc_id))
        for doc in documents
    ]
    cards = [
        SummaryCard(
            kind="summary",
            title="全库概览",
            content=f"全库共 {len(documents)} 份资料：{'、'.join(titles)}。",
            sources=[str(doc.doc_id) for doc in documents],
        )
    ]
    numeric = _numeric_sentences(documents)
    if numeric:
        content = "；".join(numeric[:4]).strip()
        if not content.endswith(("。", "；")):
            content += "。"
        cards.append(
            SummaryCard(
                kind="rule",
                title="借阅与资格规则",
                content=content[:MAX_CARD_CHARS],
                sources=[str(doc.doc_id) for doc in documents],
            )
        )
    return cards


def _extract_array(raw: str) -> list[Any] | None:
    """从可能带 ```json 围栏的模型输出里抠出 JSON 数组。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
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


def parse_cards(raw: str) -> list[SummaryCard]:
    """把模型输出洗成卡片列表；任何不合格项直接丢弃。"""
    parsed = _extract_array(raw)
    if parsed is None:
        return []
    cards: list[SummaryCard] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        title = entry.get("title")
        content = entry.get("content")
        if kind not in ("summary", "rule"):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        sources = entry.get("sources")
        cards.append(
            SummaryCard(
                kind=kind,
                title=title.strip()[:20],
                content=content.strip()[:MAX_CARD_CHARS],
                sources=[str(item) for item in sources] if isinstance(sources, list) else [],
            )
        )
        if len(cards) >= MAX_CARDS:
            break
    return cards


def corpus_digest(documents: Sequence[Any]) -> str:
    """语料摘要：用来判断「摘要卡是不是基于当前这批资料生成的」。"""
    digest = hashlib.sha256()
    for doc in documents:
        digest.update(str(getattr(doc, "doc_id", "")).encode("utf-8"))
        digest.update(b"\x00")
        digest.update((getattr(doc, "text", "") or "").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def build_corpus_text(documents: Sequence[Any], limit: int = 6000) -> str:
    """拼一份给 LLM 看的语料正文；超长时按资料均分预算，不整份截断。"""
    if not documents:
        return ""
    budget = max(500, limit // max(1, len(documents)))
    blocks: list[str] = []
    for doc in documents:
        title = getattr(doc, "title", "") or getattr(doc, "name", "") or ""
        text = (getattr(doc, "text", "") or "")[:budget]
        blocks.append(f"【资料 {getattr(doc, 'doc_id', '')}】{title}\n{text}")
    return "\n\n".join(blocks)


def to_chunk_rows(user_id: int, task_id: str, cards: Sequence[SummaryCard]) -> list[dict[str, Any]]:
    """把卡片转成切片行，形状与普通切片完全一致（同一套 upsert 与落库路径）。

    @param user_id 归属用户（向量库按它隔离）
    @param task_id 本次建库任务（摘要卡与普通片段同任务分区）
    @param cards 卡片
    @return 切片行列表，chunk_id 形如 `D00-C001`
    """
    rows: list[dict[str, Any]] = []
    for index, card in enumerate(cards, start=1):
        content = card.content.strip()
        if not content:
            continue
        rows.append(
            {
                "chunk_id": f"D{SUMMARY_DOC_NO:02d}-C{index:03d}",
                "doc_id": SUMMARY_DOC_ID,
                "doc_title": SUMMARY_DOC_TITLE,
                "heading_path": card.title,
                "excerpt": content,
                "start": 0,
                "end": len(content),
                "score": 0.0,
                "score_stage": "dense",
                "kind": card.kind,
                "verified": True,
            }
        )
    return rows


def generate(
    provider: Any,
    documents: Sequence[Any],
    timeout: float = SUMMARY_TIMEOUT_S,
) -> list[SummaryCard]:
    """调用 provider 生成摘要卡；失败返回空列表（**不抛异常**）。

    为什么是同步的（与 `suggestions.generate` 的 async 不同）
    ---------------------------------------------------------
    建库跑在 FastAPI 的 `BackgroundTasks` 里，那是**线程池里的同步函数**；
    再套一层 `asyncio.run` 会与「当前线程已有事件循环」的场合冲突。这里走
    provider 的同步补全路径 `complete_sync()`，语义等价且没有循环嵌套问题。

    失败策略（与提示词 §5.3 一致）
    ------------------------------
    * mock provider：不调模型，直接给确定性卡片（门禁要能离线断言卡片存在）；
    * real provider 生成/解析失败 → **返回空列表**，绝不拿确定性卡片冒充。
      后者会让「LLM 挂了」这件事在界面上看不出来 —— 用户以为摘要是模型总结的，
      其实是我们按数字正则抽的句子。

    @param provider LLM provider
    @param documents 本次建库的语料
    @param timeout 保留参数（同步路径靠 provider 自己的 timeout）
    @return 卡片列表；失败或语料为空时为空列表
    """
    if not documents:
        return []
    if getattr(provider, "is_mock", False):
        return mock_cards(documents)
    corpus = build_corpus_text(documents)
    if not corpus.strip():
        return []
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": corpus},
    ]
    complete_sync = getattr(provider, "complete_sync", None)
    if complete_sync is None:
        logger.warning("provider 未提供 complete_sync，本次建库不生成摘要卡")
        return []
    try:
        raw = complete_sync(messages, temperature=0.2, max_tokens=600)
    except Exception as exc:  # noqa: BLE001 - 摘要失败绝不能让建库失败
        logger.warning("摘要卡生成失败，本次建库降级为无摘要卡：%s", exc)
        return []
    cards = parse_cards(raw)
    if not cards:
        logger.warning("摘要卡输出无法解析为合格卡片，本次建库降级为无摘要卡")
    return cards


def cards_digest(cards: Sequence[SummaryCard]) -> str:
    """卡片内容摘要，写进 manifest 用来判断「摘要卡是不是这一批语料生成的」。"""
    digest = hashlib.sha256()
    for card in cards:
        digest.update(card.kind.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(card.content.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]
