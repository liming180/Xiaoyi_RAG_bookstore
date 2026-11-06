"""跨 J6/J7 共用的 Python 服务装配加载器。

为什么单独放一个文件：`server-ai` 不是安装包，测试要靠 `sys.path` 注入才能 import；
J6（内部契约）与 J7（用户隔离）都需要同一个「清掉已加载的 app.* → 重新 import」的动作，
抄两份迟早会漂移。

注意：`monkeypatch.syspath_prepend` 与 `monkeypatch.setenv` 都由调用方的 fixture 提供，
这样环境变量在用例结束后自动还原，不会污染同进程里的其它用例。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def load_app(monkeypatch, token: str):
    """把 `server-ai` 挂到 sys.path 顶端，设好内部令牌，返回新装配的 `app.main` 模块。"""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "server-ai"))
    monkeypatch.setenv("INTERNAL_TOKEN", token)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    return importlib.import_module("app.main")
