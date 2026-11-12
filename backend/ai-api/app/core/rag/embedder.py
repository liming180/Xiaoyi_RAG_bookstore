"""向量化：OpenAI 兼容 `/embeddings` 客户端 + 确定性 mock 实现。

两条实现共用同一接口，切换只由 `AI_PROVIDER` 决定，**不改变调用方的代码路径**，
这样「离线门禁」与「真实 provider」跑的是同一条管线。

真实实现（`HttpEmbedder`）的要点：
* 分批（默认 8 条）提交，单批失败按指数退避重试 3 次；
* 413 / 400（批量过大）时对半拆分重试，避免整份文档因一条超长文本全灭；
* 返回向量维度以服务端为准，首次成功后缓存，供建集合时使用。
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any, Sequence

import httpx

from ...config import Settings

# mock 档的固定维度：只要同一份语料两次运行得到同样的向量即可，
# 不追求语义质量，门禁只验证「形状、范围、稳定性」。
MOCK_DIM = 64


class EmbeddingError(RuntimeError):
    """向量化失败；调用方据此把任务置为 FAILED 而不是静默降级。"""


class Embedder:
    """向量化接口。"""

    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class MockEmbedder(Embedder):
    """确定性哈希向量：同文本永远同向量，不同文本余弦相似度可区分。"""

    def __init__(self, dim: int = MOCK_DIM) -> None:
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        # 用 sha256 派生出 dim 个 [-1, 1] 的分量，再做 L2 归一化。
        seed = hashlib.sha256((text or "").encode("utf-8")).digest()
        raw: list[float] = []
        counter = 0
        while len(raw) < self.dim:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for offset in range(0, len(block), 2):
                if len(raw) >= self.dim:
                    break
                value = int.from_bytes(block[offset : offset + 2], "big")
                raw.append(value / 32767.5 - 1.0)
            counter += 1
        norm = math.sqrt(sum(item * item for item in raw)) or 1.0
        return [round(item / norm, 8) for item in raw]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]


class HttpEmbedder(Embedder):
    """OpenAI 兼容向量化客户端（智谱 / OpenAI / 本地 vLLM 均可）。"""

    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.embedding_endpoint.rstrip("/")
        self._model = settings.embedding_model
        self._api_key = settings.embedding_api_key
        self._batch = max(1, settings.embedding_batch_size)
        self._timeout = max(1, settings.embedding_timeout_ms) / 1000.0
        self.dim = max(0, settings.embedding_dim)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post(self, batch: list[str]) -> list[list[float]]:
        payload = {"model": self._model, "input": batch}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = httpx.post(
                    f"{self._endpoint}/embeddings",
                    json=payload,
                    headers=self._headers(),
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:  # 连接层问题，可重试
                last_error = exc
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue

            if response.status_code == 200:
                body = response.json()
                rows = body.get("data") or []
                if len(rows) != len(batch):
                    raise EmbeddingError(
                        f"embedding 返回条数不符：请求 {len(batch)} 条，返回 {len(rows)} 条"
                    )
                vectors = [list(map(float, row["embedding"])) for row in rows]
                if self.dim == 0 and vectors:
                    self.dim = len(vectors[0])
                return vectors

            # 批量过大：对半拆开分别提交，不再盲目重试同一批。
            if response.status_code in (400, 413) and len(batch) > 1:
                middle = len(batch) // 2
                return self._post(batch[:middle]) + self._post(batch[middle:])

            if response.status_code in (401, 403):
                raise EmbeddingError(
                    f"embedding 鉴权失败（HTTP {response.status_code}）：请检查 EMBEDDING_API_KEY"
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = EmbeddingError(
                    f"embedding 暂时不可用（HTTP {response.status_code}）：{response.text[:200]}"
                )
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            raise EmbeddingError(
                f"embedding 失败（HTTP {response.status_code}）：{response.text[:200]}"
            )

        raise EmbeddingError(f"embedding 重试耗尽：{last_error}")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            vectors.extend(self._post(list(texts[start : start + self._batch])))
        return vectors


def embedder_from_settings(settings: Settings) -> Embedder:
    """按 `AI_PROVIDER` 选实现；real 档缺配置时由 `Settings.validate()` 提前拦住。"""
    if settings.ai_provider.lower() == "real":
        return HttpEmbedder(settings)
    return MockEmbedder()


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度；空向量返回 0，避免除零。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def normalize(vector: Sequence[float]) -> list[float]:
    """L2 归一化；Milvus 侧统一用 COSINE，入库前归一可省一次计算。"""
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [float(item) / norm for item in vector]


def as_payload(text: str) -> dict[str, Any]:
    """构造 Milvus 动态字段里要存的原文，便于调试时肉眼核对。"""
    return {"excerpt": text}
