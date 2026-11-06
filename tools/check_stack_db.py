"""一次性：核对 mysql 容器里的表数、Flyway 历史与文档归属。

用法：python tools/check_stack_db.py
"""
from __future__ import annotations

import subprocess
import sys

import local_mysql as L

ENV_FILE = "deploy/local-mysql.env"
COMPOSE = "deploy/docker-compose.yml"


def main() -> int:
    cfg = L.config()
    database = cfg["MYSQL_DATABASE"]
    sql = "; ".join(
        [
            f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{database}'",
            "SELECT GROUP_CONCAT(CONCAT(version, ':', success) ORDER BY installed_rank) FROM flyway_schema_history",
            "SELECT GROUP_CONCAT(CONCAT(uploaded_by, '=', c) ORDER BY uploaded_by) "
            "FROM (SELECT uploaded_by, COUNT(*) AS c FROM document WHERE deleted = 0 GROUP BY uploaded_by) t",
            "SELECT GROUP_CONCAT(CONCAT(user_id, '=', c) ORDER BY user_id) "
            "FROM (SELECT user_id, COUNT(*) AS c FROM chunk GROUP BY user_id) t",
        ]
    )
    result = subprocess.run(
        [
            "docker", "compose", "-f", COMPOSE, "--env-file", ENV_FILE,
            "exec", "-T", "-e", f"MYSQL_PWD={cfg['MYSQL_PASSWORD']}", "mysql",
            "mysql", "-u", "xiaoyi", "-N", "-B", "-D", database, "-e", sql,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(f"[check-stack-db] 失败：{(result.stderr or '').strip()}", file=sys.stderr)
        return 1
    rows = [line for line in (result.stdout or "").splitlines() if line.strip()]
    labels = ["tables", "flyway", "documentsByUser", "chunksByUser"]
    print(f"[check-stack-db] database={database}")
    for label, row in zip(labels, rows, strict=False):
        print(f"[check-stack-db] {label}={row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
