"""向量库：Milvus（真实）与内存（离线门禁）两套实现，接口一致。

为什么需要两套：门禁的 J3/J5 在 `AI_PROVIDER=mock` 下跑，不能依赖外部 Milvus；
而 A2/A3 的真实验收必须落在 Milvus 上，验证 `user_id` / `task_id` 过滤与删除语义。

**可见性**（实测 Milvus v3.0.0 + pymilvus 3.0.2，集合默认 Bounded 一致性）：

- 写完立刻 `query()` / `search()` 看不到新行，删完立刻 `query()` 仍能看到旧行；
- `flush()` 能让两者都立刻生效，但一次要 8–11 秒 —— 建库路径上会直接撞穿
  J4 的 15s 轮询阈值（实测单份资料从 6s 涨到 19s）；
- 读侧声明 `consistency_level="Strong"` 同样能立刻看到写入与删除（实测 0.05s）。

所以写侧与删侧都**不 flush**，可见性由 `search()` / `count()` 的 Strong 一致性保证。
代价是每次读取多一次时间戳协商，相对于 8–11 秒的 flush 可以忽略。

**隔离**：所有读写都带 `user_id` 条件，且 `search()` 的 filter 恒包含
`user_id == <当前用户>`，绝不依赖调用方自己拼过滤条件。
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Sequence

from ...config import Settings
from ..rag.embedder import cosine

# 集合里除了向量之外的标量字段。动态字段关闭时这些必须显式声明。
SCALAR_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "doc_id",
    "doc_title",
    "heading_path",
    "excerpt",
    "start",
    "end",
    "kind",
    "verified",
    "task_id",
    "doc_no",
)

PRIMARY_FIELD = "id"
VECTOR_FIELD = "vector"

# 逐行标量：由切片产出，每行一个值。
# 必须排除 task_id —— 它属于任务级，由 upsert 的入参给出；若混进这个循环，
# `row.get("task_id")` 取不到值会把刚设好的 task_id 覆盖成空串，
# 结果是写入成功、但 `task_id == "..."` 的过滤永远命中 0 行（踩过）。
ROW_SCALARS: tuple[str, ...] = tuple(name for name in SCALAR_FIELDS if name != "task_id")


def row_id(user_id: int, task_id: str, chunk_id: str) -> int:
    """由 (user, task, chunk) 派生的稳定主键，重放同一任务不会插重复行。"""
    digest = hashlib.sha256(f"{user_id}|{task_id}|{chunk_id}".encode("utf-8")).digest()
    # 取前 8 字节并清掉符号位，保证落在 int64 正区间。
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


class VectorStore:
    """向量库接口。"""

    def ensure(self, dim: int) -> None:
        raise NotImplementedError

    def upsert(self, user_id: int, task_id: str, rows: Sequence[dict[str, Any]]) -> int:
        raise NotImplementedError

    def delete_task(self, user_id: int, task_id: str) -> None:
        raise NotImplementedError

    def delete_user(self, user_id: int) -> None:
        raise NotImplementedError

    def search(
        self,
        user_id: int,
        task_id: str,
        vector: Sequence[float],
        k: int,
        doc_ids: Iterable[str] | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def count(self, user_id: int, task_id: str | None = None) -> int:
        raise NotImplementedError


def _clamp_score(score: float) -> float:
    """把余弦相似度压进契约要求的 0..1。

    余弦本身的值域是 -1..1，Milvus 的 COSINE 度量会如实返回负值；而
    `InternalCitation.score` 声明的是 `minimum: 0 / maximum: 1`，负分会直接被
    JSON Schema 判非法（Java 侧反序列化同样按契约走）。这里做一次截断，
    语义上就是「完全不相关及以下都算 0」。
    """
    return round(max(0.0, min(1.0, float(score))), 6)


def _row_to_hit(row: dict[str, Any], score: float) -> dict[str, Any]:
    """把存储行整理成检索结果，字段名与 InternalCitation 对齐。"""
    return {
        "chunk_id": row["chunk_id"],
        "doc_id": row["doc_id"],
        "doc_title": row.get("doc_title", ""),
        "heading_path": row.get("heading_path", ""),
        "excerpt": row.get("excerpt", ""),
        "start": int(row.get("start", 0)),
        "end": int(row.get("end", 0)),
        "kind": row.get("kind", "chunk"),
        "verified": bool(row.get("verified", True)),
        "score": _clamp_score(score),
    }


class MemoryVectorStore(VectorStore):
    """进程内实现：按 (user_id, task_id) 分组保存，检索走纯 Python 余弦。"""

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], list[dict[str, Any]]] = {}
        self._dim = 0

    def ensure(self, dim: int) -> None:
        self._dim = dim

    def upsert(self, user_id: int, task_id: str, rows: Sequence[dict[str, Any]]) -> int:
        bucket = self._rows.setdefault((user_id, task_id), [])
        by_id = {row["chunk_id"]: row for row in bucket}
        for row in rows:
            by_id[row["chunk_id"]] = dict(row)
        self._rows[(user_id, task_id)] = list(by_id.values())
        return len(rows)

    def delete_task(self, user_id: int, task_id: str) -> None:
        self._rows.pop((user_id, task_id), None)

    def delete_user(self, user_id: int) -> None:
        for key in [key for key in self._rows if key[0] == user_id]:
            self._rows.pop(key, None)

    def search(
        self,
        user_id: int,
        task_id: str,
        vector: Sequence[float],
        k: int,
        doc_ids: Iterable[str] | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        allowed_docs = set(doc_ids) if doc_ids else None
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self._rows.get((user_id, task_id), []):
            if allowed_docs is not None and row["doc_id"] not in allowed_docs:
                continue
            if kind and row.get("kind") != kind:
                continue
            scored.append((cosine(vector, row["vector"]), row))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [_row_to_hit(row, score) for score, row in scored[: max(0, k)]]

    def count(self, user_id: int, task_id: str | None = None) -> int:
        if task_id is not None:
            return len(self._rows.get((user_id, task_id), []))
        return sum(len(rows) for (uid, _), rows in self._rows.items() if uid == user_id)


class MilvusVectorStore(VectorStore):
    """Milvus 实现。集合名与维度由 settings 决定，首次使用时按需建集合。"""

    def __init__(self, settings: Settings) -> None:
        self._uri = settings.milvus_uri
        self._collection = settings.milvus_collection
        self._client: Any = None
        self._dim = 0

    # ---- 连接与建表 ----

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确提示
            raise RuntimeError(
                "AI_PROVIDER=real 且配置了 MILVUS_URI，但当前环境没有 pymilvus；"
                "请把 pymilvus 加进 requirements 或改用 mock 档"
            ) from exc
        self._client = MilvusClient(uri=self._uri)
        return self._client

    def ensure(self, dim: int) -> None:
        if dim <= 0:
            raise ValueError("向量维度必须为正数")
        client = self._ensure_client()
        if client.has_collection(self._collection):
            self._dim = dim
            return
        client.create_collection(
            collection_name=self._collection,
            dimension=dim,
            metric_type="COSINE",
            auto_id=False,
            id_type="int",
            primary_field=PRIMARY_FIELD,
            vector_field=VECTOR_FIELD,
            enable_dynamic_field=True,
        )
        self._dim = dim

    # ---- 写入与删除 ----

    def upsert(self, user_id: int, task_id: str, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        client = self._ensure_client()
        payload: list[dict[str, Any]] = []
        for row in rows:
            item = {
                PRIMARY_FIELD: row_id(user_id, task_id, row["chunk_id"]),
                VECTOR_FIELD: list(row["vector"]),
                "user_id": user_id,
                "task_id": task_id,
            }
            for field in ROW_SCALARS:
                value = row.get(field)
                if field == "verified":
                    item[field] = bool(value)
                elif field in ("start", "end", "doc_no"):
                    item[field] = int(value or 0)
                else:
                    item[field] = "" if value is None else str(value)
            payload.append(item)
        client.upsert(collection_name=self._collection, data=payload)
        # 这里刻意**不 flush**。实测（Milvus v3.0.0 + pymilvus 3.0.2）：
        # - 集合默认 Bounded 一致性，写完立刻 query/search 看不到新行；
        # - flush 一次要 8–11 秒，建库路径上会直接把单份资料的耗时推到 15s 以上；
        # - 读取侧声明 consistency_level="Strong" 就能立刻看到（实测 0.05s）。
        # 所以可见性交给读侧的 Strong 一致性，写侧不再付 flush 的代价。
        return len(payload)

    def delete_task(self, user_id: int, task_id: str) -> None:
        client = self._ensure_client()
        if not client.has_collection(self._collection):
            return
        client.delete(
            collection_name=self._collection,
            filter=f'user_id == {int(user_id)} and task_id == "{task_id}"',
        )
        # 同样不 flush：删完立刻 query 仍能看到旧行（默认一致性），但 Strong 读看不到
        # （实测 query(Strong) 返回 0 行）。检索走 Strong，所以旧片段不会被召回。

    def delete_user(self, user_id: int) -> None:
        client = self._ensure_client()
        if not client.has_collection(self._collection):
            return
        client.delete(collection_name=self._collection, filter=f"user_id == {int(user_id)}")

    # ---- 检索 ----

    def _filter(
        self,
        user_id: int,
        task_id: str,
        doc_ids: Iterable[str] | None,
        kind: str | None,
    ) -> str:
        clauses = [f"user_id == {int(user_id)}", f'task_id == "{task_id}"']
        allowed = [doc for doc in (doc_ids or []) if doc]
        if allowed:
            joined = ", ".join(f'"{doc}"' for doc in allowed)
            clauses.append(f"doc_id in [{joined}]")
        if kind:
            clauses.append(f'kind == "{kind}"')
        return " and ".join(clauses)

    def search(
        self,
        user_id: int,
        task_id: str,
        vector: Sequence[float],
        k: int,
        doc_ids: Iterable[str] | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self._ensure_client()
        if not client.has_collection(self._collection):
            return []
        hits = client.search(
            collection_name=self._collection,
            data=[list(vector)],
            limit=max(1, k),
            filter=self._filter(user_id, task_id, doc_ids, kind),
            output_fields=list(SCALAR_FIELDS),
            search_params={"metric_type": "COSINE"},
            # 写入与删除都不 flush（见 upsert/delete_task 的注释），可见性靠这里保证：
            # 刚建完库立刻检索必须能看到，刚删掉的旧片段必须立刻消失。
            consistency_level="Strong",
        )
        if not hits:
            return []
        return [
            _row_to_hit(hit.get("entity") or {}, hit.get("distance", 0.0))
            for hit in hits[0]
        ]

    def count(self, user_id: int, task_id: str | None = None) -> int:
        client = self._ensure_client()
        if not client.has_collection(self._collection):
            return 0
        expression = f"user_id == {int(user_id)}"
        if task_id is not None:
            expression += f' and task_id == "{task_id}"'
        rows = client.query(
            collection_name=self._collection,
            filter=expression,
            output_fields=["chunk_id"],
            limit=16384,
            consistency_level="Strong",
        )
        return len(rows)


def store_from_settings(settings: Settings) -> VectorStore:
    """有 MILVUS_URI 就用 Milvus，否则回落到内存实现（离线门禁）。"""
    if settings.milvus_uri.strip():
        return MilvusVectorStore(settings)
    return MemoryVectorStore()
