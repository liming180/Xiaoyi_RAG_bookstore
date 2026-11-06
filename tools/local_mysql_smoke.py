"""本地 MySQL 直连验收冒烟：登录 → 上传 → 建库 → 查片段 → 双用户隔离。

在 `python tools/local_mysql.py up` 起好服务之后运行，验证：
1. 登录拿到真实 JWT；
2. 上传 Markdown 落库；
3. 建库任务 SUCCEEDED 且 chunks 落库；
4. 双用户互不看见；
5. 数据库目标确实是 deploy/local-mysql.env 里配置的独立库。
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import local_mysql as L  # noqa: E402

BASE = "http://127.0.0.1:8080/api/v1"


def login(username: str, password: str) -> str:
    req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())["data"]["token"]


def upload(token: str, name: str, body: str) -> dict:
    boundary = "X"
    payload = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\n"
        "Content-Type: text/markdown\r\n\r\n" + body + f"\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/documents",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req).read())


def rebuild(token: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/index/rebuild",
        data=json.dumps({"chunkSize": 180, "overlap": 30}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req).read())


def wait_task(token: str, task_id: int, timeout: float = 60) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(
            f"{BASE}/index/tasks/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        task = json.loads(urllib.request.urlopen(req).read())["data"]
        if task["status"] in ("SUCCEEDED", "FAILED"):
            return task
        time.sleep(0.5)
    raise TimeoutError(f"task {task_id} did not finish in {timeout}s")


def list_chunks(token: str) -> list:
    req = urllib.request.Request(f"{BASE}/chunks", headers={"Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req).read())["data"]


def main() -> int:
    cfg = L.config()
    a = login(cfg["AUTH_BOOTSTRAP_USERNAME"], cfg["AUTH_BOOTSTRAP_PASSWORD"])
    b = login(cfg["AUTH_SECONDARY_BOOTSTRAP_USERNAME"], cfg["AUTH_SECONDARY_BOOTSTRAP_PASSWORD"])
    print(f"[smoke] login ok db={cfg['MYSQL_DATABASE']}")

    up_a = upload(a, "a.md", "# A\n\nAlpha body.\n")
    up_b = upload(b, "b.md", "# B\n\nBravo body.\n")
    assert up_a["code"] == 0 and up_b["code"] == 0
    doc_a = up_a["data"]["accepted"][0]["id"]
    print(f"[smoke] upload ok doc_a={doc_a}")

    task_a = rebuild(a)["data"]
    print(f"[smoke] rebuild task={task_a['id']} status={task_a['status']}")
    final = wait_task(a, task_a["id"])
    assert final["status"] == "SUCCEEDED", final
    assert final["chunkCount"] >= 1
    print(f"[smoke] rebuild SUCCEEDED chunks={final['chunkCount']}")

    chunks_a = list_chunks(a)
    chunks_b = list_chunks(b)
    assert chunks_a and not chunks_b
    print(f"[smoke] isolation ok A={len(chunks_a)} B={len(chunks_b)}")

    # 确认目标库
    with L.connect(cfg, cfg["MYSQL_DATABASE"]) as conn:
        cur = conn.cursor()
        cur.execute("select count(*) from document")
        doc_count = cur.fetchone()[0]
        cur.execute("select count(*) from chunk")
        chunk_count = cur.fetchone()[0]
        cur.execute("select username from user order by id")
        users = [x[0] for x in cur.fetchall()]
    print(f"[smoke] {cfg['MYSQL_DATABASE']} doc={doc_count} chunk={chunk_count} users={users}")
    assert doc_count >= 2 and chunk_count >= 1
    assert cfg["AUTH_BOOTSTRAP_USERNAME"] in users and cfg["AUTH_SECONDARY_BOOTSTRAP_USERNAME"] in users
    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
