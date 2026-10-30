"""会话状态：history / mode / k，以及清空对话（对应 F6 / F7 / F10 / 拓展A）。"""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .settings import AppError, K_DEFAULT, K_MAX, K_MIN, load_config

MODES = {"rag", "direct", "both"}

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "session_id": uuid.uuid4().hex[:12],
    "history": [],
    "mode": "rag",
    "k": K_DEFAULT,
}


def new_session() -> dict[str, Any]:
    """清空对话：history 归零、换新 session_id；mode 与 k 保持不变（拓展A）。"""
    with _LOCK:
        _STATE["session_id"] = uuid.uuid4().hex[:12]
        _STATE["history"] = []
    return snapshot()


def set_params(mode: str | None = None, k: int | None = None) -> dict[str, Any]:
    """切换模式或改 k 都会清空 history —— 避免跨模式串话（F6）。"""
    with _LOCK:
        changed = False
        if mode is not None:
            if mode not in MODES:
                raise AppError(f"模式只能是 {', '.join(sorted(MODES))}。")
            if mode != _STATE["mode"]:
                _STATE["mode"] = mode
                changed = True
        if k is not None:
            if not isinstance(k, int) or isinstance(k, bool) or not K_MIN <= k <= K_MAX:
                raise AppError(f"k 须为 {K_MIN} 至 {K_MAX} 的整数。")
            if k != _STATE["k"]:
                _STATE["k"] = k
                changed = True
        if changed:
            _STATE["history"] = []
            _STATE["session_id"] = uuid.uuid4().hex[:12]
    return snapshot()


def snapshot() -> dict[str, Any]:
    with _LOCK:
        return {
            "session_id": _STATE["session_id"],
            "mode": _STATE["mode"],
            "k": _STATE["k"],
            "history_len": len(_STATE["history"]),
            "history": [dict(item) for item in _STATE["history"]],
        }


def get_history() -> list[dict[str, str]]:
    with _LOCK:
        return [dict(item) for item in _STATE["history"]]


def set_history(history: list[dict[str, str]]) -> None:
    """仅供 both 模式在两次调用之间还原历史，避免互相污染。"""
    with _LOCK:
        _STATE["history"] = [dict(item) for item in history]


def append_turn(question: str, answer: str, user_content: str | None = None) -> None:
    """一轮成功问答后写入 history；user 侧保留实际发送的内容（含参考资料）。"""
    with _LOCK:
        _STATE["history"].append({"role": "user", "content": user_content or question})
        _STATE["history"].append({"role": "assistant", "content": answer})


def current_k() -> int:
    with _LOCK:
        return _STATE["k"]


def current_mode() -> str:
    with _LOCK:
        return _STATE["mode"]


def default_k() -> int:
    return int(load_config().get("top_k", K_DEFAULT))
