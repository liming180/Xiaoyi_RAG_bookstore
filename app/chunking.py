"""字符滑窗分块、资料读取与 manifest 构造（对应 F1 / F2 / F3 的后端）。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .settings import ALLOWED_SUFFIXES, AppError, UNVERIFIED_SOURCES


def chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    """滑窗分块，返回 [(start, end, 片段正文)]；相邻片段共享 overlap 个字符。"""
    if not isinstance(size, int) or isinstance(size, bool) or not isinstance(overlap, int) or isinstance(overlap, bool):
        raise AppError("分块参数须为整数，且 0 <= chunk_overlap < chunk_size。")
    if size <= 0 or overlap < 0 or overlap >= size:
        raise AppError("分块参数须为整数，且 0 <= chunk_overlap < chunk_size。")
    result: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        result.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = end - overlap
    return result


def read_doc(path: Path) -> str:
    """以 utf-8-sig 读取（兼容带/不带 BOM），统一换行，拒绝空正文。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(f"{path.name} 不是 UTF-8 编码，请另存为 UTF-8。") from None
    except OSError as exc:
        raise AppError(f"{path.name} 读取失败：{exc}") from None
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise AppError(f"{path.name} 没有正文，已跳过。")
    return text


def list_docs(data_dir: Path) -> list[Path]:
    """只取 .md/.txt，按文件名排序（决定 D01..D06 的编号顺序）。"""
    if not data_dir.is_dir():
        raise AppError("data 目录不存在。")
    files = [
        p for p in data_dir.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES
    ]
    files.sort(key=lambda p: p.name)
    return files


def load_chunks(data_dir: Path, size: int, overlap: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """读取全部资料并分块，返回 (chunks, sources)。

    chunk 字段：chunk_id / source / start / end / text / verified
    sources 字段：source / sha256
    """
    chunk_text("", size, overlap)          # 参数校验前置
    files = list_docs(data_dir)
    if not files:
        raise AppError("data 目录里没有 .md 或 .txt 资料，请先添加资料。")
    chunks: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    for doc_no, path in enumerate(files, 1):
        text = read_doc(path)
        sources.append({
            "source": path.name,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
        verified = path.name not in UNVERIFIED_SOURCES
        for number, (start, end, body) in enumerate(chunk_text(text, size, overlap), 1):
            chunks.append({
                "chunk_id": f"D{doc_no:02d}-C{number:03d}",
                "source": path.name,
                "start": start,
                "end": end,
                "text": body,
                "verified": verified,
            })
    return chunks, sources


def manifest_for(cfg: dict[str, Any], sources: list[dict[str, str]]) -> dict[str, Any]:
    """建库有效性的判定依据：模型 + 接口 + 分块参数 + 每份资料 SHA256。"""
    return {
        "embedding_model": cfg.get("embedding_model", ""),
        "embedding_endpoint": cfg.get("embedding_endpoint", ""),
        "chunk_size": cfg.get("chunk_size"),
        "chunk_overlap": cfg.get("chunk_overlap"),
        "sources": sources,
    }


def doc_stats(data_dir: Path, size: int, overlap: int) -> list[dict[str, Any]]:
    """资料列表（文件名 / 字数 / 片段数 / 是否核实），供 F1 侧栏使用。"""
    stats: list[dict[str, Any]] = []
    for path in list_docs(data_dir):
        try:
            text = read_doc(path)
        except AppError as exc:
            stats.append({
                "name": path.name, "chars": 0, "chunks": 0,
                "verified": path.name not in UNVERIFIED_SOURCES, "error": str(exc),
            })
            continue
        stats.append({
            "name": path.name,
            "chars": len(text),
            "chunks": len(chunk_text(text, size, overlap)),
            "verified": path.name not in UNVERIFIED_SOURCES,
        })
    return stats
