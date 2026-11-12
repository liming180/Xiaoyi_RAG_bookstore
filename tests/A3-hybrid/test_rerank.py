"""精排语义、服务顺序、降级保序与中文 BM25。

这里的用例锁的是**实测得出的契约**，不是直觉：

* `LexicalReranker`（无 rerank 服务时的降级）必须**保序**。
  `tools/a3_compare.py` 在 6 问 6 语料、真实 embedding 上量过：纯词面重排 top-1 3/6、
  0.6/0.4 加权 4/6、0.85/0.15 加权 4/6，而不重排的 RRF 是 5/6。
  降级路径的底线是「不比不降级更差」，所以顺序原样保留，词项分只做并列消歧。
* `HttpReranker` 必须以**服务返回的数组顺序**为准。智谱 rerank 的 relevance_score
  会饱和成 1.0/1.0/1.0，按分数重排等于用 chunk_id 字典序覆盖服务顺序，
  实测会把正确片段挤出 top-k。
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server-ai"))

from app.config import Settings
from app.core.rag.reranker import HttpReranker, LexicalReranker, QueryRewriter
from app.core.rag.retriever import Bm25Index, tokenize


DOCS = [
    {"chunk_id": "D01-C001", "excerpt": "空间使用需要预约，签到后入场。", "score": 0.9},
    {"chunk_id": "D02-C001", "excerpt": "普通图书最多借4本，借期21天，可以续借一次。", "score": 0.8},
    {"chunk_id": "D03-C001", "excerpt": "读书会活动时间另行通知。", "score": 0.7},
]
QUESTION = "普通图书最多能借几本，借期多久？"


def settings(**overrides) -> Settings:
    return Settings(internal_token="test-token", **overrides)


def test_lexical_reranker_preserves_fusion_order() -> None:
    ranked = LexicalReranker().rerank(QUESTION, DOCS, 3)
    assert [row["chunk_id"] for row in ranked] == [row["chunk_id"] for row in DOCS]
    # 分数必须仍是融合分：轨迹里「第 1 名分数比第 2 名低」会直接矛盾。
    assert [row["score"] for row in ranked] == [0.9, 0.8, 0.7]
    assert [row["rrf_score"] for row in ranked] == [0.9, 0.8, 0.7]


def test_lexical_reranker_keeps_lexical_score_for_tie_break() -> None:
    tied = [
        {"chunk_id": "D01-C001", "excerpt": "读书会活动时间另行通知。", "score": 0.5},
        {"chunk_id": "D02-C001", "excerpt": "普通图书最多借4本，借期21天。", "score": 0.5},
    ]
    ranked = LexicalReranker().rerank(QUESTION, tied, 2)
    # 融合分并列时，词面更贴题的 D02 应排前，但分数不改写。
    assert [row["chunk_id"] for row in ranked] == ["D02-C001", "D01-C001"]
    assert all(row["score"] == 0.5 for row in ranked)
    assert ranked[0]["lexical_score"] > ranked[1]["lexical_score"]


def test_http_rerank_honours_service_order_not_scores() -> None:
    """分数有区分度时，顺序必须是服务给的顺序（不按分数二次排序）。"""
    payload = {"results": [
        {"index": 2, "relevance_score": 0.92},
        {"index": 0, "relevance_score": 0.71},
        {"index": 1, "relevance_score": 0.33},
    ]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/paas/v4/rerank"
        body = __import__("json").loads(request.content)
        # 必须请求全部候选，否则淘汰区丢失。
        assert body["top_n"] == len(DOCS)
        return httpx.Response(200, json=payload)

    reranker = HttpReranker(settings(rerank_endpoint="https://open.bigmodel.cn/api/paas/v4/rerank"))
    import unittest.mock

    original = httpx.Client
    with unittest.mock.patch(
        "httpx.Client",
        side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    ):
        ranked = reranker.rerank(QUESTION, DOCS, 3)

    assert [row["chunk_id"] for row in ranked] == ["D03-C001", "D01-C001", "D02-C001"]
    assert [row["score"] for row in ranked] == [0.92, 0.71, 0.33]
    assert not reranker.degraded


def test_http_rerank_detects_saturated_scores_and_falls_back() -> None:
    """智谱实测：20 个候选全被压到 1.0 附近（极差 <1e-5），此时顺序不可信。

    不设这道闸的话，服务返回的近似随机顺序会覆盖 RRF，
    实测 space-booking 的 top-1 命中从 5/6 掉到 2/6。
    """
    payload = {"results": [
        {"index": 2, "relevance_score": 1.0},
        {"index": 0, "relevance_score": 0.9999951},
        {"index": 1, "relevance_score": 0.9999925},
    ]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    reranker = HttpReranker(settings(rerank_endpoint="https://open.bigmodel.cn/api/paas/v4/rerank"))
    import unittest.mock

    original = httpx.Client
    with unittest.mock.patch(
        "httpx.Client",
        side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    ):
        ranked = reranker.rerank(QUESTION, DOCS, 3)

    # 饱和 → 退回保序，与不重排完全一致
    assert [row["chunk_id"] for row in ranked] == [row["chunk_id"] for row in DOCS]
    assert reranker.degraded
    assert "饱和" in reranker.reason


def test_http_rerank_appends_unranked_candidates() -> None:
    """服务只回了部分候选时，剩下的按原融合顺序接在后面。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.9}]})

    reranker = HttpReranker(settings(rerank_endpoint="https://example.invalid/rerank"))
    import unittest.mock

    original = httpx.Client
    with unittest.mock.patch(
        "httpx.Client",
        side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    ):
        ranked = reranker.rerank(QUESTION, DOCS, 3)

    assert [row["chunk_id"] for row in ranked] == ["D02-C001", "D01-C001", "D03-C001"]


def test_failed_rerank_degrades_to_order_preserving_fallback() -> None:
    reranker = HttpReranker(settings(rerank_endpoint="http://127.0.0.1:1/rerank", rerank_timeout_ms=50))
    ranked = reranker.rerank(QUESTION, DOCS, 3)
    assert len(ranked) == 3
    assert reranker.degraded
    assert "降级" in reranker.reason
    # 降级后必须与不重排等价，不能比它更差。
    assert [row["chunk_id"] for row in ranked] == [row["chunk_id"] for row in DOCS]


def test_query_rewrite_failure_uses_original() -> None:
    rewriter = QueryRewriter(settings(ai_provider="real", llm_endpoint="http://127.0.0.1:1", llm_timeout_ms=50))
    history = [{"role": "user", "content": "那借期呢？"}]
    assert rewriter.rewrite("可以借几本？", history) == "可以借几本？"
    assert rewriter.degraded


def test_no_history_skips_rewrite_call() -> None:
    rewriter = QueryRewriter(settings(ai_provider="real", llm_endpoint="http://127.0.0.1:1"))
    assert rewriter.rewrite("借书规则", []) == "借书规则"
    assert not rewriter.degraded


def test_chinese_bm25_rewards_exact_terms_and_tokenizes_numbers() -> None:
    assert "4" in tokenize("最多借4本")
    index = Bm25Index(DOCS)
    ranked = index.top(QUESTION, 3)
    assert ranked[0]["chunk_id"] == "D02-C001"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_bm25_does_not_contain_other_scope_rows() -> None:
    # 索引只接收调用方限定后的 rows；即使查询精确匹配外部文档也不会出现。
    index = Bm25Index([DOCS[0]])
    assert all(row["chunk_id"] == "D01-C001" for row in index.top("借书证", 20))
