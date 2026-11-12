"""按用户隔离的持久化状态（SQLite）。

所有读写都带 user_id 条件，任何调用方都无法跨用户拿到任务、文档或切片。
持久化文件固定落在 ``Path(settings.storage_root) / "ai-state.sqlite3"``。
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings
from ..core.rag.splitter import MAX_DOCS_PER_USER

# 重启恢复时写入的失败原因（中文，说明服务重启导致中断）。
RESTART_ERROR = "服务重启导致任务中断，请重新提交解析任务"

# 允许通过 update_task 更新的字段白名单。
_TASK_FIELDS = frozenset({"status", "stage", "progress", "doc_count", "chunk_count", "error", "finished_at"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    submission_key TEXT NOT NULL,
    generation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    doc_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    finished_at INTEGER,
    chunk_size INTEGER NOT NULL DEFAULT 180,
    overlap INTEGER NOT NULL DEFAULT 30
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_user_submission ON tasks (user_id, submission_key);
CREATE INDEX IF NOT EXISTS ix_tasks_user_status ON tasks (user_id, status, created_at);

CREATE TABLE IF NOT EXISTS documents (
    user_id INTEGER NOT NULL,
    doc_id TEXT NOT NULL,
    doc_no INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PARSING',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, doc_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    user_id INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_title TEXT NOT NULL DEFAULT '',
    heading_path TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    start INTEGER NOT NULL DEFAULT 0,
    end_offset INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0.9,
    score_stage TEXT NOT NULL DEFAULT 'rerank',
    kind TEXT NOT NULL DEFAULT 'chunk',
    verified INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS ix_chunks_user_task ON chunks (user_id, task_id);
"""

_lock = threading.RLock()
_connection: sqlite3.Connection | None = None
_connection_path: Path | None = None


def database_path() -> Path:
    """返回持久化文件路径，父目录不存在时创建。"""
    target = Path(get_settings().storage_root) / "ai-state.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _connect() -> sqlite3.Connection:
    """取得当前进程内的连接，路径变化时重建（便于测试切换 storage_root）。"""
    global _connection, _connection_path
    target = database_path()
    with _lock:
        if _connection is not None and _connection_path == target:
            return _connection
        if _connection is not None:
            _connection.close()
        connection = sqlite3.connect(str(target), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        connection.executescript(_SCHEMA)
        connection.commit()
        _connection = connection
        _connection_path = target
        return connection


def close() -> None:
    """关闭连接，供测试或进程退出时清理。"""
    global _connection, _connection_path
    with _lock:
        if _connection is not None:
            _connection.close()
        _connection = None
        _connection_path = None


def initialize() -> None:
    """建表并打开连接，启动钩子调用。"""
    _connect()


def recover_interrupted() -> int:
    """把重启前遗留的 PENDING/RUNNING 任务标记为 FAILED，返回处理条数。"""
    connection = _connect()
    now = int(time.time())
    with _lock:
        rows = connection.execute(
            "SELECT task_id FROM tasks WHERE status IN ('PENDING', 'RUNNING')"
        ).fetchall()
        connection.execute(
            "UPDATE tasks SET status = 'FAILED', stage = 'done', progress = 100, error = ?, finished_at = ? "
            "WHERE status IN ('PENDING', 'RUNNING')",
            (RESTART_ERROR, now),
        )
        connection.commit()
    return len(rows)


def create_task(
    user_id: int,
    submission_key: str,
    generation: str,
    doc_count: int,
    chunk_size: int,
    overlap: int,
) -> tuple[str, bool]:
    """按 (user_id, submission_key) 幂等创建任务，返回 (任务号, 是否新建)。"""
    connection = _connect()
    now = int(time.time())
    with _lock:
        row = connection.execute(
            "SELECT task_id FROM tasks WHERE user_id = ? AND submission_key = ?",
            (user_id, submission_key),
        ).fetchone()
        if row is not None:
            return str(row["task_id"]), False
        task_id = "task-" + uuid.uuid4().hex[:12]
        connection.execute(
            "INSERT INTO tasks (task_id, user_id, submission_key, generation, status, stage, progress, "
            "doc_count, chunk_count, error, created_at, finished_at, chunk_size, overlap) "
            "VALUES (?, ?, ?, ?, 'PENDING', 'parsing', 0, ?, 0, '', ?, NULL, ?, ?)",
            (task_id, user_id, submission_key, generation, doc_count, now, chunk_size, overlap),
        )
        connection.commit()
        return task_id, True


def _task_view(row: sqlite3.Row) -> dict[str, Any]:
    """把任务行转换成内部契约要求的字段形状。"""
    return {
        "task_id": row["task_id"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": int(row["progress"]),
        "doc_count": int(row["doc_count"]),
        "chunk_count": int(row["chunk_count"]),
        "error": row["error"],
        "created_at": int(row["created_at"]),
        "finished_at": None if row["finished_at"] is None else int(row["finished_at"]),
    }


def get_task(user_id: int, task_id: str) -> dict[str, Any] | None:
    """按用户读取任务，跨用户返回 None。"""
    connection = _connect()
    with _lock:
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    return _task_view(row) if row is not None else None


def update_task(user_id: int, task_id: str, **fields: Any) -> None:
    """更新任务进度字段，字段名不在白名单内直接忽略。"""
    updates = {name: value for name, value in fields.items() if name in _TASK_FIELDS}
    if not updates:
        return
    assignments = ", ".join(f"{name} = ?" for name in updates)
    values = list(updates.values()) + [task_id, user_id]
    connection = _connect()
    with _lock:
        connection.execute(
            f"UPDATE tasks SET {assignments} WHERE task_id = ? AND user_id = ?",
            values,
        )
        connection.commit()


def latest_succeeded_task(user_id: int) -> dict[str, Any] | None:
    """取该用户最近一次成功任务，用于检索范围与索引清单。"""
    connection = _connect()
    with _lock:
        row = connection.execute(
            "SELECT * FROM tasks WHERE user_id = ? AND status = 'SUCCEEDED' "
            "ORDER BY finished_at DESC, rowid DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    view = _task_view(row)
    view["chunk_size"] = int(row["chunk_size"])
    view["overlap"] = int(row["overlap"])
    return view


def upsert_document(user_id: int, doc_id: str, title: str, status: str, chunk_count: int) -> int:
    """写入或更新用户自己的文档状态，返回该用户内的文档序号。

    序号是 chunk_id 里的两位十进制（`D01-C001`），所以一个用户**同时**最多 99 份。
    新文档取当前最小的空闲号而不是 `MAX(doc_no)+1`：删除资料后腾出来的号要能被复用，
    否则「累计上传过 99 份」就等于「永久报废」——实测踩过，第 100 份起全部被压成
    D99，同批 upsert 主键重复，Milvus 报 code=1100。
    """
    connection = _connect()
    now = int(time.time())
    with _lock:
        row = connection.execute(
            "SELECT doc_no FROM documents WHERE user_id = ? AND doc_id = ?",
            (user_id, doc_id),
        ).fetchone()
        if row is None:
            used = {
                int(item["doc_no"])
                for item in connection.execute(
                    "SELECT doc_no FROM documents WHERE user_id = ?", (user_id,)
                ).fetchall()
            }
            doc_no = next((slot for slot in range(1, MAX_DOCS_PER_USER + 1) if slot not in used), 0)
            if doc_no == 0:
                raise ValueError(
                    f"资料数已达上限：用户 {user_id} 同时最多 {MAX_DOCS_PER_USER} 份"
                    "（chunk_id 的文档号只有两位）；请先删除不再需要的资料再建库"
                )
            connection.execute(
                "INSERT INTO documents (user_id, doc_id, doc_no, title, status, chunk_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, doc_id, doc_no, title, status, chunk_count, now),
            )
        else:
            doc_no = int(row["doc_no"])
            connection.execute(
                "UPDATE documents SET title = ?, status = ?, chunk_count = ?, updated_at = ? "
                "WHERE user_id = ? AND doc_id = ?",
                (title, status, chunk_count, now, user_id, doc_id),
            )
        connection.commit()
    return doc_no


def reconcile_documents(user_id: int, doc_ids: Iterable[str], *, before: int) -> int:
    """回收本次建库资料集之外、且在 `before` 之前登记的文档，返回释放的条数。

    Java 侧删除资料不会通知 Python，状态库里的 `documents` 行会一直留着、把 99 个编号
    慢慢吃光。每次建库前拿请求里的全量资料集对账，把已删除的资料连切片一起清掉。

    两条约束都是踩出来的：

    1. **必须先于编号分配执行**，否则「已达上限」会在回收腾出空位之前就把任务判死；
    2. **只删 `updated_at < before` 的行**。同一用户的两次建库在时间上可能重叠
       （Python 后台线程按 `INGEST_STAGE_DELAY_MS` 分段推进），后一个任务刚登记的
       资料绝不能因为不在前一个任务的资料集里就被删掉 —— 实测报过
       「资料 495 尚未登记编号，无法生成 chunk_id」。

    不做编号重排：分配取最小空闲号，删掉的行腾出的空位自然会被下一次分配用上，
    而重排会在并发任务之间改动对方正在使用的编号。
    """
    keep = {str(doc_id) for doc_id in doc_ids if doc_id}
    connection = _connect()
    with _lock:
        rows = connection.execute(
            "SELECT doc_id, updated_at FROM documents WHERE user_id = ?", (user_id,)
        ).fetchall()
        stale = [
            str(item["doc_id"])
            for item in rows
            if str(item["doc_id"]) not in keep and int(item["updated_at"]) < before
        ]
        for doc_id in stale:
            connection.execute(
                "DELETE FROM chunks WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
            )
            connection.execute(
                "DELETE FROM documents WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
            )
        connection.commit()
    return len(stale)


def document_number(user_id: int, doc_id: str) -> int:
    """读取文档在该用户内的序号，不存在时返回 0。"""
    connection = _connect()
    with _lock:
        row = connection.execute(
            "SELECT doc_no FROM documents WHERE user_id = ? AND doc_id = ?",
            (user_id, doc_id),
        ).fetchone()
    return int(row["doc_no"]) if row is not None else 0


def get_document(user_id: int, doc_id: str) -> dict[str, Any] | None:
    """按用户读取文档状态，跨用户返回 None。"""
    connection = _connect()
    with _lock:
        row = connection.execute(
            "SELECT doc_id, status, chunk_count FROM documents WHERE user_id = ? AND doc_id = ?",
            (user_id, doc_id),
        ).fetchone()
    if row is None:
        return None
    return {"doc_id": row["doc_id"], "status": row["status"], "chunk_count": int(row["chunk_count"])}


def replace_chunks(user_id: int, task_id: str, doc_id: str, parts: list[dict[str, Any]]) -> None:
    """替换该用户某文档的全部切片（先删后插，保证重复解析不残留）。"""
    connection = _connect()
    with _lock:
        connection.execute(
            "DELETE FROM chunks WHERE user_id = ? AND doc_id = ?",
            (user_id, doc_id),
        )
        connection.executemany(
            "INSERT OR REPLACE INTO chunks (user_id, chunk_id, task_id, doc_id, doc_title, heading_path, "
            "excerpt, start, end_offset, score, score_stage, kind, verified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    user_id,
                    part["chunk_id"],
                    task_id,
                    part["doc_id"],
                    part["doc_title"],
                    part["heading_path"],
                    part["excerpt"],
                    part["start"],
                    part["end"],
                    part["score"],
                    part["score_stage"],
                    part["kind"],
                    1 if part["verified"] else 0,
                )
                for part in parts
            ],
        )
        connection.commit()


def list_chunks(user_id: int, task_id: str) -> list[dict[str, Any]]:
    """读取该用户指定任务下的切片，返回检索需要的字段。"""
    connection = _connect()
    with _lock:
        rows = connection.execute(
            "SELECT * FROM chunks WHERE user_id = ? AND task_id = ? ORDER BY chunk_id",
            (user_id, task_id),
        ).fetchall()
    return [
        {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "doc_title": row["doc_title"],
            "heading_path": row["heading_path"],
            "excerpt": row["excerpt"],
            "start": int(row["start"]),
            "end": int(row["end_offset"]),
            "score": float(row["score"]),
            "score_stage": row["score_stage"],
            "kind": row["kind"],
            "verified": bool(row["verified"]),
        }
        for row in rows
    ]
