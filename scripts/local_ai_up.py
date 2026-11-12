"""本机 MySQL 验收：前台托管 Python AI 服务（uvicorn）。

用法（由 pwsh 的 run_in_background 启动）::

    python scripts/local_ai_up.py

与 p7_up.start_python 的差别：不脱离父进程，日志直接进 stdout，
由 harness 的后台作业托管；STORAGE_ROOT 指向 local-mysql/ai，
与 Java 的落盘目录分开，避免 ai-state.sqlite3 被测试清理占用。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import p7_env  # noqa: E402


def main() -> int:
    cfg = p7_env.load()
    storage = ROOT / "test-artifacts" / "local-mysql" / "ai"
    storage.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        INTERNAL_TOKEN=cfg["INTERNAL_TOKEN"],
        STORAGE_ROOT=str(storage),
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
    )
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000",
        # 与 scripts/p7_up.py:start_python 保持一致：uvicorn 默认 5s 回收空闲连接，
        # JDK HttpClient 会复用被回收的连接，表现为随机 Connection reset → 50301。
        "--timeout-keep-alive", "75",
    ]
    print(f"[local-ai-up] storage={storage}", flush=True)
    print(f"[local-ai-up] token={cfg['INTERNAL_TOKEN'][:8]}...", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT / "services" / "ai-api"), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
