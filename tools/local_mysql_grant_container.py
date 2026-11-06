"""给「容器连宿主机 MySQL」场景建一个专用账号。

容器里连宿主机 3306 时，来源地址是 Docker 网关（172.x），MySQL 里
`root@localhost` / `lmj@localhost` 都匹配不上，必须有一个 `'%'` 主机位的账号。
这个脚本只做三件事：建账号、改口令、只授本库权限。

    python tools/local_mysql_grant_container.py
    python tools/local_mysql_grant_container.py --user xiaoyi --database xiaoyi_rag_local_gate
"""
from __future__ import annotations

import argparse
import sys

import local_mysql as L

# 注意：pymysql 只在 execute(sql, args) 带参数时才做 `sql % args`。所以
#   - 带 %s 占位的语句里，字面量百分号要写 %%；
#   - 不带参数的语句里，必须写单个 %，否则 MySQL 会把 '%%' 当成一个不存在的主机位，
#     报 (1410, 'You are not allowed to create a user with GRANT')。
CREATE = "CREATE USER IF NOT EXISTS {user}@'%%' IDENTIFIED BY %s"
ALTER = "ALTER USER {user}@'%%' IDENTIFIED BY %s"
GRANT = "GRANT ALL PRIVILEGES ON `{database}`.* TO {user}@'%'"
SHOW_GRANTS = "SHOW GRANTS FOR {user}@'%'"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="xiaoyi")
    parser.add_argument("--database")
    args = parser.parse_args()

    cfg = L.config()
    database = args.database or cfg["MYSQL_DATABASE"]
    password = cfg["MYSQL_PASSWORD"]
    user = args.user

    conn = L.connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(CREATE.format(user=user), (password,))
        # CREATE USER IF NOT EXISTS 不会更新既有账号的口令，显式 ALTER 一次保证一致。
        cur.execute(ALTER.format(user=user), (password,))
        cur.execute(GRANT.format(user=user, database=database))
        cur.execute("FLUSH PRIVILEGES")
        cur.execute("SELECT user, host FROM mysql.user ORDER BY user, host")
        rows = cur.fetchall()
        cur.execute(
            "SELECT user, host FROM mysql.user WHERE user = %s", (user,)
        )
        created = cur.fetchall()
        cur.execute(SHOW_GRANTS.format(user=user))
        grants = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    print(f"[grant] 账号 {user}@'%' 就绪：{created}")
    print(f"[grant] 库 {database} 已授权")
    for line in grants:
        print("        " + line)
    print("[grant] 全部账号：")
    for name, host in rows:
        print(f"        {name}@{host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
