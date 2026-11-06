"""临时诊断：打印门禁库最近的任务与资料行，用于排查 P7 验收项。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p7_up  # noqa: E402
import pymysql  # noqa: E402

pw = p7_up.env_or_user_registry("MYSQL_PASSWORD")
conn = pymysql.connect(
    host="127.0.0.1",
    port=3306,
    user="root",
    password=pw,
    database="xiaoyi_rag_gate",
    charset="utf8mb4",
)
with conn.cursor() as cur:
    cur.execute(
        "select id,user_id,status,stage,progress,submission_key,external_task_id,created_at"
        " from index_task order by id desc limit 10"
    )
    print("--- index_task ---")
    for row in cur.fetchall():
        print(row)
    cur.execute("select id,title,status,uploaded_by from document order by id desc limit 6")
    print("--- document ---")
    for row in cur.fetchall():
        print(row)
    cur.execute("show index from index_task")
    print("--- index_task indexes ---")
    for row in cur.fetchall():
        print(row[2], row[4], row[1])
conn.close()
