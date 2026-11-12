"""中文稀疏召回：自管 jieba 分词，在 Python 内建 BM25 倒排。

为什么不用 LangChain BM25Retriever：它用空白切分，中文整句几乎变成一个词。
这里由调用方传入当前用户、当前任务的切片，索引只在那个范围内构建，
因此稀疏路不会绕过向量路的 user_id/task_id 隔离。
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+(?:[.-][a-zA-Z0-9_]+)*")
_STOP_WORDS = {"的", "了", "吗", "呢", "是", "有", "和", "与", "在", "能", "我", "你", "请", "问", "一下"}
_USER_WORDS = (
    "借书证", "图书证", "读书会", "普通图书", "工具书", "续借", "预约", "签到",
    "借用", "借期", "取书", "押金", "门禁", "开放日", "年末书单分享会",
)


def tokenize(text: str) -> list[str]:
    """中英混排分词：保留数字/编号，不把中文句子交给空白切分。"""
    import jieba  # 延迟导入，让无需稀疏路的 mock 进程可运行

    result: list[str] = []
    for part in _TOKEN_RE.findall((text or "").lower()):
        if re.fullmatch(r"[a-zA-Z0-9_]+(?:[.-][a-zA-Z0-9_]+)*", part):
            result.append(part)
        else:
            result.extend(word.strip() for word in jieba.cut(part, cut_all=False))
    return [word for word in result if word and word not in _STOP_WORDS]


def configure_dictionary() -> None:
    """为项目语料补自定义词；重复调用不会重复插入。"""
    import jieba

    for word in _USER_WORDS:
        jieba.add_word(word)


class Bm25Index:
    """一份不可变 BM25 索引；用 IDF 非负变体避免常见词得负分。"""

    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]
        self.tokens = [tokenize(str(row.get("excerpt", ""))) for row in self.rows]
        self.frequencies = [Counter(tokens) for tokens in self.tokens]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.average_length = sum(self.lengths) / len(self.rows) if self.rows else 0.0
        self.document_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            self.document_frequency.update(set(tokens))

    def score(self, query: str, *, k1: float = 1.5, b: float = 0.75) -> list[dict[str, Any]]:
        """返回全部行的稀疏得分，未排序；query 无有效词时全为 0。"""
        total = len(self.rows)
        if not total:
            return []
        query_tokens = tokenize(query)
        scores = [0.0] * total
        for term in query_tokens:
            nq = self.document_frequency.get(term, 0)
            if not nq:
                continue
            # Robertson IDF 的下限截断：避免高频词出现负分、降低文档相关性。
            idf = max(0.0, math.log((total - nq + 0.5) / (nq + 0.5) + 1.0))
            for index, frequency in enumerate(self.frequencies):
                tf = frequency.get(term, 0)
                if not tf:
                    continue
                denominator = tf + k1 * (1.0 - b + b * self.lengths[index] / max(self.average_length, 1e-9))
                scores[index] += idf * tf * (k1 + 1.0) / denominator
        return [{**self.rows[index], "score": score} for index, score in enumerate(scores)]

    def top(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        ranked = sorted(self.score(query), key=lambda row: (-row["score"], row["chunk_id"]))
        return ranked[: max(0, limit)]


class Bm25Cache:
    """按 (user_id, task_id, scope) 缓存索引；内容条数变化时失效。

    `scope` 是这次建索引用的**子集标识**（`kind` 与 `doc_ids` 拼出来的串）。不带上它
    会出真错：`kind=summary` 与 `kind=rule` 的语料条数常常相同（都是 1 条），
    revision 相等就让缓存把摘要卡的倒排表当成规则卡的返回 —— 实测表现为
    「问规则，引用里混进统计卡」，而两次查询在代码里看起来毫无关联。
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[int, str, str], tuple[int, Bm25Index]] = {}
        self._lock = threading.Lock()
        self._configured = False

    def build(
        self, user_id: int, task_id: str, rows: Sequence[dict[str, Any]], scope: str = "",
    ) -> Bm25Index:
        """建/取倒排索引。

        @param user_id 归属用户
        @param task_id 建库任务号
        @param rows 本次参与倒排的切片（已按 kind / doc_ids 过滤）
        @param scope 子集标识，见类注释
        @return 倒排索引
        """
        key = (int(user_id), str(task_id), str(scope))
        revision = len(rows)
        with self._lock:
            if not self._configured:
                configure_dictionary()
                self._configured = True
            cached = self._entries.get(key)
            if cached and cached[0] == revision:
                return cached[1]
        # 大语料构建不持锁，避免阻塞其他用户；最终同 key 写入的仍是等价索引。
        index = Bm25Index(rows)
        with self._lock:
            self._entries[key] = (revision, index)
        return index

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


bm25_cache = Bm25Cache()
