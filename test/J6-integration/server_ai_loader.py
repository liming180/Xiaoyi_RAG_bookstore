from __future__ import annotations

import importlib
import sys
from pathlib import Path


def load_app(monkeypatch, token: str):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "server-ai"))
    monkeypatch.setenv("INTERNAL_TOKEN", token)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    return importlib.import_module("app.main")
