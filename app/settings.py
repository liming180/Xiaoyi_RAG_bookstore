"""配置与路径。所有路径都基于项目根目录，Key 只存内存或环境变量。"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVAL_DIR = ROOT / "eval"
WEB_DIR = ROOT / "frontend"
# Vue 3 + Vite 的构建产物目录；前端源码在 WEB_DIR/src，产物在 WEB_DIR/dist。
# 运行时只需要 dist（index.html + assets），源码与 node_modules 都不参与服务。
# 旧的 web/ 目录已删除（与 frontend/ 冲突），此常量指向新的 frontend/。
WEB_DIST = WEB_DIR / "dist"
WEB_ENTRY = WEB_DIST / "index.html"
LOG_DIR = ROOT / "logs"
EXPORT_DIR = ROOT / "exports"
INDEX_FILE = ROOT / "index.json"
CONFIG_FILE = ROOT / "config.json"
CONFIG_EXAMPLE = ROOT / "config.example.json"
QUESTIONS_CSV = ROOT / "questions.csv"
KEYWORDS_CSV = EVAL_DIR / "keywords.csv"

ALLOWED_SUFFIXES = {".md", ".txt"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# 教师给定的干扰/不可信清单：文件名白名单判定可信度（F11）
UNVERIFIED_SOURCES = {"06_成员留言摘录.md"}

DEFAULTS: dict[str, Any] = {
    "provider": "mock",          # mock = 离线模拟；real = 教师提供的真实接口
    "endpoint": "",
    "model": "",
    "embedding_endpoint": "",
    "embedding_model": "",
    "timeout_seconds": 45,
    "temperature": None,
    "max_tokens": None,
    "chunk_size": 180,
    "chunk_overlap": 30,
    "top_k": 3,
    "embedding_batch_size": 8,
    "mock_embedding_dim": 256,
    "port": 8765,
}

# 前端可选范围（指导书：k 在 1~5 调整，默认 3；片段长度 50~1000）
K_MIN, K_MAX, K_DEFAULT = 1, 5, 3
SIZE_MIN, SIZE_MAX = 50, 1000


class AppError(RuntimeError):
    """可直接展示给用户的中文错误。"""


def _reject_constant(value: str) -> None:
    raise ValueError("JSON 不能包含非有限数值。")


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON 数值超出范围。")
    return number


def load_config() -> dict[str, Any]:
    """读取 config.json，缺失字段用默认值补齐；缺失文件时整体用默认值（mock 档）。"""
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.is_file():
        try:
            loaded = json.loads(
                CONFIG_FILE.read_text(encoding="utf-8-sig"),
                parse_constant=_reject_constant,
                parse_float=_parse_float,
            )
        except (OSError, ValueError) as exc:
            raise AppError(f"config.json 读取失败：{exc}") from None
        if not isinstance(loaded, dict):
            raise AppError("config.json 顶层必须是对象。")
        cfg.update({k: v for k, v in loaded.items() if k in DEFAULTS or k == "provider"})
    if not cfg.get("provider"):
        cfg["provider"] = "mock"
    return cfg


def save_config_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """把允许修改的字段写回 config.json（绝不写 Key）。"""
    editable = {
        "provider", "endpoint", "model", "embedding_endpoint", "embedding_model",
        "timeout_seconds", "temperature", "max_tokens", "chunk_size",
        "chunk_overlap", "top_k", "embedding_batch_size", "mock_embedding_dim", "port",
    }
    cfg = load_config()
    for key, value in patch.items():
        if key in editable:
            cfg[key] = value
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return cfg


def runtime_keys() -> tuple[str, str]:
    """Key 只从内存注入或环境变量取，不落盘、不进日志。"""
    chat = _MEMORY_KEYS.get("chat_key") or os.environ.get("RAG_CHAT_KEY", "")
    embed = _MEMORY_KEYS.get("embed_key") or os.environ.get("RAG_EMBED_KEY", "") or chat
    return chat, embed


_MEMORY_KEYS: dict[str, str] = {}


def set_runtime_keys(chat_key: str, embed_key: str) -> None:
    if chat_key:
        _MEMORY_KEYS["chat_key"] = chat_key.strip()
    if embed_key:
        _MEMORY_KEYS["embed_key"] = embed_key.strip()
    elif chat_key:
        _MEMORY_KEYS["embed_key"] = chat_key.strip()


def has_keys() -> bool:
    chat, embed = runtime_keys()
    return bool(chat and embed)


def is_mock(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config()
    return cfg.get("provider", "mock") != "real"


def ensure_dirs() -> None:
    for path in (DATA_DIR, EVAL_DIR, LOG_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
