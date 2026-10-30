"""知识库索引的读写与有效性校验，以及运行日志（对应 F2 / F3 / F4 的持久层）。"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import chunking, embedding
from .settings import AppError, DATA_DIR, INDEX_FILE, LOG_DIR, is_mock, load_config, runtime_keys

_LOCK = threading.Lock()
_BUILD_STATE: dict[str, Any] = {"stage": "idle", "done": 0, "total": 0, "docs": 0, "chunks": 0, "message": "", "error": ""}


def _chunk_settings(cfg: dict[str, Any]) -> tuple[int, int]:
    size = cfg.get("chunk_size")
    overlap = cfg.get("chunk_overlap")
    if not isinstance(size, int) or isinstance(size, bool) or not isinstance(overlap, int) or isinstance(overlap, bool):
        raise AppError("chunk_size 与 chunk_overlap 须为整数。")
    if not 50 <= size <= 1000:
        raise AppError("片段长度须在 50 至 1000 之间。")
    if not 0 <= overlap < size:
        raise AppError("重叠字数须满足 0 <= 重叠 < 片段长度。")
    return size, overlap


# ------------------------------------------------------------------ 建库
def build_index(progress=None) -> dict[str, Any]:
    """分批嵌入并原子写入 index.json；progress(stage, done, total) 用于前端进度。"""
    cfg = load_config()
    size, overlap = _chunk_settings(cfg)
    embedding.validate_embedding_config(cfg)
    _, embed_key = runtime_keys()

    chunks, sources = chunking.load_chunks(DATA_DIR, size, overlap)
    batch = cfg.get("embedding_batch_size", 8)
    if not isinstance(batch, int) or isinstance(batch, bool) or batch < 1:
        raise AppError("embedding_batch_size 须为正整数。")

    total = len(chunks)
    if progress:
        progress("embedding", 0, total)
    vectors: list[list[float]] = []
    for start in range(0, total, batch):
        piece = chunks[start:start + batch]
        vectors.extend(embedding.embed_texts(cfg, embed_key, [c["text"] for c in piece]))
        if progress:
            progress("embedding", min(start + batch, total), total)

    if len(vectors) != total:
        raise AppError("嵌入接口返回的向量条数与片段数不一致，请教师核对接入层。")
    dims = {len(v) for v in vectors}
    if len(dims) != 1:
        raise AppError(f"嵌入向量维度不一致：{sorted(dims)}，请重新建库。")
    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector

    index = {"manifest": chunking.manifest_for(cfg, sources), "chunks": chunks}
    destination = INDEX_FILE
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="\n",
            dir=destination.parent, prefix=destination.name + ".",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(index, stream, ensure_ascii=False, indent=2, allow_nan=False)
        temporary.replace(destination)
    except (OSError, TypeError, ValueError):
        raise AppError("知识库保存失败，请检查目录和写入权限；原文件未被替换。") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    if progress:
        progress("done", total, total)
    return {"docs": len(sources), "chunks": total, "manifest": index["manifest"]}


def build_index_async() -> None:
    """后台线程建库，前端轮询 /api/index/progress。"""
    if _BUILD_STATE["stage"] in {"reading", "embedding"}:
        raise AppError("正在建库，请等待当前任务完成。")

    def progress(stage: str, done: int, total: int) -> None:
        _BUILD_STATE.update({"stage": stage, "done": done, "total": total})

    def worker() -> None:
        _BUILD_STATE.update({"stage": "reading", "done": 0, "total": 0, "error": "", "message": ""})
        try:
            with _LOCK:
                result = build_index(progress)
            _BUILD_STATE.update({
                "stage": "done", "done": result["chunks"], "total": result["chunks"],
                "docs": result["docs"], "chunks": result["chunks"],
                "message": f"建库成功，文档 {result['docs']} 份，片段 {result['chunks']} 条。",
            })
        except AppError as exc:
            _BUILD_STATE.update({"stage": "error", "error": str(exc), "message": str(exc)})
        except Exception as exc:                     # noqa: BLE001
            _BUILD_STATE.update({"stage": "error", "error": f"建库失败：{exc}", "message": str(exc)})

    threading.Thread(target=worker, daemon=True).start()


def build_state() -> dict[str, Any]:
    return dict(_BUILD_STATE)


# ------------------------------------------------------------------ 读库与校验
def read_index() -> dict[str, Any]:
    """五层校验：存在/格式 → manifest 全等 → 片段数 → 逐片段与原文重切一致 → 向量维度。"""
    cfg = load_config()
    size, overlap = _chunk_settings(cfg)
    expected_chunks, sources = chunking.load_chunks(DATA_DIR, size, overlap)
    try:
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise AppError("尚未建库，请先点击“重新建库”。") from None
    except (OSError, ValueError, UnicodeError):
        raise AppError("index.json 已损坏，请重新建库。") from None
    if not isinstance(index, dict) or "manifest" not in index or "chunks" not in index:
        raise AppError("index.json 结构不符，请重新建库。")
    if index["manifest"] != chunking.manifest_for(cfg, sources):
        raise AppError("资料、分块或嵌入模型已改变，请重新建库。")
    stored = index["chunks"]
    if not isinstance(stored, list) or len(stored) != len(expected_chunks):
        raise AppError("资料、分块或嵌入模型已改变，请重新建库。")
    expected_fields = {"chunk_id", "source", "start", "end", "text", "verified"}
    for got, want in zip(stored, expected_chunks):
        if not isinstance(got, dict) or set(got) != expected_fields | {"embedding"}:
            raise AppError("知识库片段字段不符，请重新建库。")
        for field in expected_fields:
            if got[field] != want[field]:
                raise AppError("资料、分块或嵌入模型已改变，请重新建库。")
        vector = got["embedding"]
        if not isinstance(vector, list) or not vector or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in vector
        ):
            raise AppError("知识库向量格式不符，请重新建库。")
    dims = {len(c["embedding"]) for c in stored}
    if len(dims) != 1:
        raise AppError("知识库向量维度不一致，请重新建库。")
    return index


def status() -> dict[str, Any]:
    """界面状态：ready / stale / 资料数 / 片段数 / manifest。"""
    cfg = load_config()
    size, overlap = _chunk_settings(cfg)
    docs = chunking.doc_stats(DATA_DIR, size, overlap)
    payload: dict[str, Any] = {
        "provider": cfg.get("provider", "mock"),
        "mock": is_mock(cfg),
        "chunk_size": size,
        "chunk_overlap": overlap,
        "top_k": int(cfg.get("top_k", 3)),
        "docs": docs,
        "doc_count": len(docs),
        "ready": False,
        "stale": False,
        "chunks": 0,
        "message": "",
        "manifest": None,
        "build": build_state(),
    }
    try:
        index = read_index()
    except AppError as exc:
        payload["message"] = str(exc)
        payload["stale"] = INDEX_FILE.is_file()
        return payload
    payload.update({
        "ready": True,
        "chunks": len(index["chunks"]),
        "manifest": index["manifest"],
        "message": f"知识库已就绪，文档 {len(index['manifest']['sources'])} 份，片段 {len(index['chunks'])} 条。",
    })
    return payload


# ------------------------------------------------------------------ 日志
def append_log(record: dict[str, Any]) -> Path:
    """每轮问答写一行 JSONL；不写任何密钥。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = LOG_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.jsonl"
    line = json.dumps(record, ensure_ascii=False, allow_nan=False)
    with path.open("a", encoding="utf-8-sig", newline="\n") as stream:
        stream.write(line + "\n")
    return path


def last_log() -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"empty": True, "message": "还没有任何问答记录。"}
    try:
        lines = files[0].read_text(encoding="utf-8-sig").strip().splitlines()
        record = json.loads(lines[-1])
    except (OSError, ValueError):
        return {"empty": True, "message": "日志读取失败。"}
    record["_file"] = files[0].name
    return record


def touch() -> None:
    """占位，便于测试时统一入口。"""
    time.sleep(0)
