"""嵌入：真实接口通道（教师提供）+ 离线模拟通道（mock）。"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

from .settings import AppError, is_mock, runtime_keys


def _no_redirect() -> urllib.request.OpenerDirector:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):   # noqa: D401
            return None

    return urllib.request.build_opener(NoRedirect())


def validate_embedding_config(cfg: dict[str, Any]) -> None:
    if is_mock(cfg):
        return
    endpoint = cfg.get("embedding_endpoint", "")
    model = cfg.get("embedding_model", "")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise AppError("embedding_endpoint 须填写完整的 HTTPS 接口地址。")
    if not isinstance(model, str) or not model.strip():
        raise AppError("embedding_model 须填写非空的模型名称。")


def _validate_vectors(vectors: list[Any], expected: int) -> None:
    if len(vectors) != expected:
        raise AppError("嵌入接口返回的向量条数与输入不一致，请教师核对接入层。")
    dims = set()
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise AppError("嵌入向量为空或格式不符。")
        for value in vector:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise AppError("嵌入向量含非有限数值。")
        dims.add(len(vector))
    if len(dims) != 1:
        raise AppError(f"嵌入向量维度不一致：{sorted(dims)}，请重新建库。")
    if all(all(v == 0 for v in vector) for vector in vectors):
        raise AppError("嵌入向量全为零，请教师核对接入层。")


# ---------------------------------------------------------------- mock 通道
def _gram_hash(gram: str, dim: int) -> int:
    """稳定的字符串哈希（不受 PYTHONHASHSEED 影响）。"""
    h = 2166136261
    for ch in gram.encode("utf-8"):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h % dim


def mock_embed_one(text: str, dim: int) -> list[float]:
    """单字 + 2-gram + 3-gram 加权哈希向量：中文短文本的近似词袋，用于离线模拟检索。

    只用 2-gram 时，“每周几几点举行”“讨论空间需要几人每次最长多久”这类问法与
    资料原文的用词差异会让无关片段排到前面（实测 T01/T05/T08 检索不到正确片段）。
    加入单字通道补关键词重合、加入低权 3-gram 补短语精确度后，10 道验收题的正确
    片段稳定落在前 3 名内（见 tools/selfcheck.py 的检索断言）。
    """
    vector = [0.0] * dim
    clean = "".join(ch for ch in text if not ch.isspace())
    if not clean:
        return vector
    weighted: list[tuple[str, float]] = [(ch, 1.0) for ch in clean]
    weighted.extend((clean[i:i + 2], 1.0) for i in range(len(clean) - 1))
    weighted.extend((clean[i:i + 3], 0.25) for i in range(len(clean) - 2))
    for gram, weight in weighted:
        vector[_gram_hash(gram, dim)] += weight
    norm = math.sqrt(math.fsum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def mock_embed(texts: list[str], dim: int = 256) -> list[list[float]]:
    return [mock_embed_one(text, dim) for text in texts]


# ---------------------------------------------------------------- 真实通道
def _real_embed(cfg: dict[str, Any], key: str, texts: list[str]) -> list[list[float]]:
    payload = json.dumps(
        {"model": cfg["embedding_model"], "input": texts},
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        cfg["embedding_endpoint"],
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with _no_redirect().open(request, timeout=cfg.get("timeout_seconds", 45)) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise AppError(f"嵌入接口返回 HTTP {exc.code}，请核对密钥与地址。") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AppError(f"嵌入接口连接失败或超时：{exc}") from None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        items = data["data"]
        ordered = sorted(items, key=lambda item: item["index"])
        vectors = [item["embedding"] for item in ordered]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise AppError("嵌入接口响应结构不符，请教师核对接入层。") from None
    return vectors


def embed_texts(cfg: dict[str, Any], key: str, texts: list[str]) -> list[list[float]]:
    """统一的嵌入入口：mock 档走本地 2-gram，real 档走教师接口。"""
    if not texts:
        return []
    if is_mock(cfg):
        return mock_embed(texts, int(cfg.get("mock_embedding_dim", 256)))
    if not key:
        raise AppError("缺少嵌入接口密钥，请先填写密钥。")
    vectors = _real_embed(cfg, key, texts)
    _validate_vectors(vectors, len(texts))
    return vectors


def embed_query(cfg: dict[str, Any], question: str) -> list[float]:
    _, embed_key = runtime_keys()
    return embed_texts(cfg, embed_key, [question])[0]
