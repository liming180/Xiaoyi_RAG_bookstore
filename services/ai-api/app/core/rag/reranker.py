"""精排与查询改写：外部服务失败时明确降级，不丢弃召回结果。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, Sequence

import httpx

from ...config import Settings
from .retriever import tokenize

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    degraded: bool
    reason: str

    def rerank(self, question: str, rows: Sequence[dict[str, Any]], k: int) -> list[dict[str, Any]]: ...


def lexical_score(question: str, text: str) -> float:
    """离线重排：查询词覆盖率 + 词频，结果固定在 0..1。"""
    query = set(tokenize(question))
    if not query:
        return 0.0
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    covered = sum(1 for word in query if word in tokens)
    occurrences = sum(tokens.count(word) for word in query)
    coverage = covered / len(query)
    frequency = occurrences / (occurrences + 4.0)
    return round(min(1.0, 0.85 * coverage + 0.15 * frequency), 6)


class LexicalReranker:
    """无 rerank 服务时的本地降级：**保序**，只用词项分做同分并列的 tie-break。

    为什么不再「按词面覆盖率重排」：`tools/a3_compare.py` 在 6 问 6 语料、真实
    embedding 上量过三种做法 —— 纯词项重排 top-1 3/6、0.6/0.4 加权 4/6、
    0.85/0.15 加权 4/6，而不做任何重排的 RRF 是 5/6。中文长问句的虚词会把覆盖率
    拉平，任何「本地启发式改写融合顺序」都只会更差。
    所以降级路径的契约是「不比不降级更差」：顺序原样保留，词项分只用于解释与并列消歧。
    真要提升排序质量必须接 `RERANK_ENDPOINT`（外部 rerank 服务），不是调权重。
    """

    degraded = True
    reason = "未配置 RERANK_ENDPOINT，保持融合顺序（本地词项分仅作并列消歧）"

    def rerank(self, question: str, rows: Sequence[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        if not rows:
            return []
        ranked = [
            {
                **row,
                "rrf_score": float(row.get("score", 0.0)),
                "lexical_score": lexical_score(question, str(row.get("excerpt", ""))),
                # score 保持融合分：轨迹与引用里的分数必须能追回 RRF 的名次，
                # 否则「第 1 名分数比第 2 名低」这种自相矛盾会直接进前端。
                "score": float(row.get("score", 0.0)),
            }
            for row in rows
        ]
        ranked.sort(key=lambda row: (-row["score"], -row["lexical_score"], row["chunk_id"]))
        return ranked[: max(0, k)]


class HttpReranker:
    """智谱 / Jina 兼容 rerank API；只信服务返回的 index，不信任任意新增字段。"""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.rerank_endpoint.strip()
        self._model = settings.rerank_model
        self._key = settings.rerank_api_key or settings.llm_api_key
        self._timeout = max(1, settings.rerank_timeout_ms) / 1000.0
        self.degraded = False
        self.reason = ""

    def rerank(self, question: str, rows: Sequence[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        if not rows:
            return []
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        payload = {
            "model": self._model,
            "query": question,
            "documents": [str(row.get("excerpt", "")) for row in rows],
            # top_n 要全量：只请求 k 条会把候选裁掉，淘汰区就没了；排序由服务做，
            # 本地再取前 k。智谱实测支持返回全部候选。
            "top_n": len(rows),
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                results = response.json().get("results")
            if not isinstance(results, list) or not results:
                raise ValueError("rerank 响应缺少 results")
            scores = [
                float(item.get("relevance_score", item.get("score", 0.0)))
                for item in results
            ]
            # 分数饱和检测：智谱 rerank 在长候选集上会把所有候选都打到 1.0 附近
            # （实测 20 个候选的极差 < 1e-5），此时它的数组顺序不可信，
            # 照抄会把 RRF 排好的结果打乱（space-booking 的 top-1 从 5/6 掉到 2/6）。
            # 判据：极差小于 0.01 视为「无区分度」，退回保序降级。
            if len(scores) > 1 and (max(scores) - min(scores)) < 0.01:
                logger.warning(
                    "rerank 分数饱和（极差 %.6f），退回保序融合", max(scores) - min(scores)
                )
                self.degraded = True
                self.reason = (
                    f"重排分数饱和（极差 {max(scores) - min(scores):.6f} < 0.01），"
                    "无区分度，已退回保序融合"
                )
                return LexicalReranker().rerank(question, rows, k)

            ranked: list[dict[str, Any]] = []
            used: set[int] = set()
            # 分数有区分度时，服务返回的数组顺序就是排名，**不要**再按分数排一次：
            # 分数只在饱和时没意义，正常时应与顺序一致；按 (-score, chunk_id) 重排
            # 会在分数接近时退化成 chunk_id 字典序，把服务顺序覆盖掉。
            for item in results:
                index = int(item["index"])
                if index < 0 or index >= len(rows) or index in used:
                    raise ValueError(f"rerank 返回非法或重复 index：{index}")
                used.add(index)
                score = float(item.get("relevance_score", item.get("score", 0.0)))
                ranked.append({
                    **rows[index],
                    "rrf_score": float(rows[index].get("score", 0.0)),
                    "score": round(max(0.0, min(1.0, score)), 6),
                })
            # 服务没排到的候选按原融合顺序接在后面，构成淘汰区。
            for index, row in enumerate(rows):
                if index not in used:
                    ranked.append({
                        **row,
                        "rrf_score": float(row.get("score", 0.0)),
                        "score": float(row.get("score", 0.0)),
                    })
            return ranked[: max(0, k)]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("rerank 降级：%s", exc)
            self.degraded = True
            self.reason = f"重排服务失败，已降级本地保序：{exc}"
            return LexicalReranker().rerank(question, rows, k)


def reranker_from_settings(settings: Settings) -> Reranker:
    if settings.rerank_endpoint.strip():
        return HttpReranker(settings)
    return LexicalReranker()


class QueryRewriter:
    """多轮指代消解：仅一次非流式 LLM 调用，失败/空结果用原查询。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.degraded = False
        self.reason = ""

    def rewrite(self, question: str, history: Sequence[dict[str, str]] | None = None) -> str:
        question = question.strip()
        if not history or self._settings.ai_provider.lower() != "real" or not self._settings.retrieval_rewrite:
            return question
        turns = "\n".join(f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in list(history)[-4:])
        prompt = (
            "把最后一问改写成可独立检索的中文问题。只输出改写后的问题，不回答、不解释；"
            "保留资料中的数字与专有名词。\n"
            f"历史：\n{turns}\n最后一问：{question}"
        )
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        payload = {
            "model": self._settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.0,
        }
        try:
            with httpx.Client(timeout=max(1, self._settings.llm_timeout_ms) / 1000.0) as client:
                response = client.post(f"{self._settings.llm_endpoint.rstrip('/')}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            rewritten = str(content).strip().splitlines()[0].strip() if content else ""
            if not rewritten or len(rewritten) > 500:
                raise ValueError("改写结果为空或过长")
            return rewritten
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            logger.warning("查询改写降级：%s", exc)
            self.degraded = True
            self.reason = f"查询改写失败，使用原问题：{exc}"
            return question

    async def rewrite_async(self, question: str, history: Sequence[dict[str, str]] | None = None) -> str:
        return await asyncio.to_thread(self.rewrite, question, history)
