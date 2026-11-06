"""本机 MySQL 验收启动器：在本进程内装配环境并前台托管 Java。

用法（由 pwsh 的 run_in_background 启动）::

    python tools/local_mysql_up.py

与 p7_java_fg 的差别：先把 MYSQL_DATABASE 切到隔离库
``xiaoyi_rag_local_gate``，再把装配好的环境变量写进 os.environ，
最后调 p7_java_fg.main()。这样 p7_env.load() 读到的是本进程内
修改后的 MYSQL_DATABASE，而不是 test-artifacts/p7-env.json 里的
xiaoyi_rag_gate。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import p7_env  # noqa: E402
import p7_up  # noqa: E402


def main() -> int:
    cfg = p7_env.load()
    cfg.update(
        MYSQL_HOST="127.0.0.1", MYSQL_PORT="3306", MYSQL_USER="root",
        MYSQL_PASSWORD=p7_up.env_or_user_registry("MYSQL_PASSWORD"),
        MYSQL_DATABASE="xiaoyi_rag_local_gate", AI_MOCK="false",
        INGEST_STAGE_DELAY_MS="0",
        STORAGE_ROOT=str(ROOT / "test-artifacts" / "local-mysql" / "java"),
        AI_STORAGE_ROOT=str(ROOT / "test-artifacts" / "local-mysql" / "ai"),
    )
    # 把装配好的变量写进本进程环境，让 p7_java_fg.main() 的 load() 读到
    env = p7_up.build_env(cfg)
    for key, value in env.items():
        if isinstance(value, str):
            os.environ[key] = value
    print(f"[local-mysql-up] target database={cfg['MYSQL_DATABASE']}", flush=True)
    import p7_java_fg
    return p7_java_fg.main()


if __name__ == "__main__":
    raise SystemExit(main())
