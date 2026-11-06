"""Compose 容器栈端到端验收（走 nginx，默认 http://127.0.0.1:8088）。

与 tools/local_mysql_smoke.py 的区别：那个跑的是宿主机直连模式，
这个验证「三个服务都在 Docker 里」的两条路径：
  - 宿主机 MySQL（docker-compose.localdb*.yml）：默认，直连 3306 核对
  - mysql 容器（docker-compose.yml）：加 --db-via-container，走 compose exec 核对

检查项：
  1. 首页可访问，且是 SPA 入口
  2. A/B 两个账号都能登录，JWT sub 不同
  3. A/B 各上传一份专属资料，列表里只看到自己的
  4. A 建库成功后，chunks 只属于 A（B 查到 0）
  5. 库核对：document/chunk 行确实落在目标库，且按用户隔离

    python tools/compose_smoke.py
    python tools/compose_smoke.py --base http://127.0.0.1:8088
    python tools/compose_smoke.py --db-via-container
    python tools/compose_smoke.py --skip-db
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import local_mysql as L

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deploy" / "local-mysql.env"


def call(base: str, path: str, method: str = "GET", body=None, token: str | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def login(base: str, username: str, password: str) -> dict:
    status, payload = call(base, "/api/v1/auth/login", "POST", {"username": username, "password": password})
    if status != 200 or payload.get("code") != 0:
        raise SystemExit(f"[compose-smoke] 登录失败 {username}: {status} {payload}")
    return payload["data"]


def upload(base: str, token: str, filename: str, text: str) -> int:
    """POST /api/v1/documents（multipart，字段名必须是 files）。

    注意不是 /documents/upload —— KnowledgeController 只注册了 POST /documents，
    打到 /documents/upload 会被 Tomcat 判成 405 再由 GlobalExceptionHandler 包成 500。
    """
    boundary = "----composesmoke"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/v1/documents",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise SystemExit(f"[compose-smoke] 上传失败: {payload}")
    accepted = payload["data"]["accepted"]
    if not accepted:
        raise SystemExit(f"[compose-smoke] 上传被跳过: {payload['data']}")
    return accepted[0]["id"]


def db_counts_direct(cfg: dict[str, str], user_a: int, user_b: int) -> tuple[int, int, int]:
    """宿主机 MySQL 形态：直连 3306 数行。

    列名不是对称的：document 用 uploaded_by，chunk 用 user_id（见 V1/V7 迁移）。
    """
    conn = L.connect(cfg, cfg["MYSQL_DATABASE"])
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM document WHERE uploaded_by = %s AND deleted = 0", (user_a,))
        docs_a = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM document WHERE uploaded_by = %s AND deleted = 0", (user_b,))
        docs_b = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM chunk WHERE user_id = %s", (user_a,))
        chunk_rows_a = cur.fetchone()[0]
    finally:
        conn.close()
    return docs_a, docs_b, chunk_rows_a


def db_counts_container(cfg: dict[str, str], user_a: int, user_b: int) -> tuple[int, int, int]:
    """mysql 容器形态：容器不发布 3306 端口，走 compose exec 查询。

    口令通过 MYSQL_PWD 环境变量传入，不出现在进程参数里。
    """
    import subprocess

    root = ROOT / "deploy" / "docker-compose.yml"
    database = cfg["MYSQL_DATABASE"]
    # deploy/local-mysql.env 的 MYSQL_USER 是宿主机模式的 root，mysql 镜像
    # 不接受 MYSQL_USER=root，容器里的业务账号是 MYSQL_USER_FOR_CONTAINER。
    user = os.getenv("MYSQL_USER_FOR_CONTAINER") or "xiaoyi"

    def query(sql: str) -> int:
        result = subprocess.run(
            [
                "docker", "compose", "-f", str(root), "--env-file", str(ENV_FILE),
                "exec", "-T", "-e", f"MYSQL_PWD={cfg['MYSQL_PASSWORD']}", "mysql",
                "mysql", "-u", user, "-N", "-B", "-D", database, "-e", sql,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"[compose-smoke] 容器内查库失败：{(result.stderr or '').strip()}")
        return int((result.stdout or "0").strip().splitlines()[0])

    return (
        query(f"SELECT COUNT(*) FROM document WHERE uploaded_by = {user_a} AND deleted = 0"),
        query(f"SELECT COUNT(*) FROM document WHERE uploaded_by = {user_b} AND deleted = 0"),
        query(f"SELECT COUNT(*) FROM chunk WHERE user_id = {user_a}"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8088")
    parser.add_argument("--skip-db", action="store_true", help="跳过直连库核对（库里只有 HTTP 层证据时用）")
    parser.add_argument("--db-via-container", action="store_true", help="数据库在 mysql 容器里，用 compose exec 查")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    cfg = L.config()
    user_a, pass_a = cfg["AUTH_BOOTSTRAP_USERNAME"], cfg["AUTH_BOOTSTRAP_PASSWORD"]
    user_b, pass_b = cfg["AUTH_SECONDARY_BOOTSTRAP_USERNAME"], cfg["AUTH_SECONDARY_BOOTSTRAP_PASSWORD"]

    # 1. 首页
    with urllib.request.urlopen(base + "/", timeout=20) as response:
        html = response.read().decode("utf-8", "replace")
    assert response.status == 200, "首页非 200"
    assert '<div id="app"' in html, "首页不是 SPA 入口"
    print(f"[compose-smoke] 首页 ok bytes={len(html)}")

    # 2. 双账号登录
    a = login(base, user_a, pass_a)
    b = login(base, user_b, pass_b)
    assert a["user"]["id"] != b["user"]["id"], "两个账号 id 相同"
    print(f"[compose-smoke] 登录 ok {user_a}(id={a['user']['id']}) / {user_b}(id={b['user']['id']})")

    # 3. 各自上传 + 列表隔离
    stamp = int(time.time())
    title_a, title_b = f"compose-A-{stamp}", f"compose-B-{stamp}"
    upload(base, a["token"], f"a-{stamp}.md", f"# {title_a}\n\n这是容器模式下 A 的资料。\n")
    upload(base, b["token"], f"b-{stamp}.md", f"# {title_b}\n\n这是容器模式下 B 的资料。\n")

    _, list_a = call(base, "/api/v1/documents", token=a["token"])
    _, list_b = call(base, "/api/v1/documents", token=b["token"])
    names_a = {d["title"] for d in list_a["data"]}
    names_b = {d["title"] for d in list_b["data"]}
    assert title_a in names_a and title_a not in names_b, "A 的资料泄漏到 B"
    assert title_b in names_b and title_b not in names_a, "B 的资料泄漏到 A"
    print(f"[compose-smoke] 列表隔离 ok A={len(names_a)} B={len(names_b)}")

    # 4. A 建库 → 只有 A 有 chunks
    status, task = call(base, "/api/v1/index/rebuild", "POST", {"chunkSize": 180, "overlap": 30}, a["token"])
    assert status in (200, 202, 409), f"建库请求异常 {status} {task}"
    task_id = task["data"]["id"] if status != 409 else None
    if task_id:
        deadline = time.time() + 120
        while time.time() < deadline:
            _, one = call(base, f"/api/v1/index/tasks/{task_id}", token=a["token"])
            if one["data"]["status"] in ("SUCCEEDED", "FAILED"):
                break
            time.sleep(1)
        assert one["data"]["status"] == "SUCCEEDED", f"建库未成功: {one['data']['status']}"
        print(f"[compose-smoke] 建库 ok task={task_id} chunks={one['data'].get('chunkCount')}")

    # 路径是 /api/v1/chunks（KnowledgeController.listChunks），不是 /index/chunks。
    _, chunks_a = call(base, "/api/v1/chunks", token=a["token"])
    _, chunks_b = call(base, "/api/v1/chunks", token=b["token"])
    count_a = len(chunks_a.get("data") or [])
    count_b = len(chunks_b.get("data") or [])
    assert count_a >= 1, "A 没有 chunk"
    assert count_b == 0, f"B 不该有 chunk，实际 {count_b}"
    print(f"[compose-smoke] chunks 隔离 ok A={count_a} B={count_b}")

    # 5. 库核对：宿主机 MySQL 直连，或 mysql 容器内 exec。
    if args.skip_db:
        docs_a = docs_b = chunk_rows_a = None
        print("[compose-smoke] 跳过库核对（--skip-db）")
    elif args.db_via_container:
        docs_a, docs_b, chunk_rows_a = db_counts_container(cfg, a["user"]["id"], b["user"]["id"])
        print(f"[compose-smoke] 库核对(container) db={cfg['MYSQL_DATABASE']} docs A={docs_a} B={docs_b} chunksA={chunk_rows_a}")
        assert docs_a >= 1 and docs_b >= 1 and chunk_rows_a >= 1, "库里的行数不对"
    else:
        docs_a, docs_b, chunk_rows_a = db_counts_direct(cfg, a["user"]["id"], b["user"]["id"])
        print(f"[compose-smoke] 库核对 db={cfg['MYSQL_DATABASE']} docs A={docs_a} B={docs_b} chunksA={chunk_rows_a}")
        assert docs_a >= 1 and docs_b >= 1 and chunk_rows_a >= 1, "库里的行数不对"

    report = {
        "pass": True,
        "base": base,
        "database": cfg["MYSQL_DATABASE"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "homepageBytes": len(html),
        "accounts": [
            {"username": user_a, "id": a["user"]["id"]},
            {"username": user_b, "id": b["user"]["id"]},
        ],
        "documents": {"A": len(names_a), "B": len(names_b)},
        "rebuild": {"taskId": task_id, "chunks": (one["data"].get("chunkCount") if task_id else None)},
        "chunks": {"A": count_a, "B": count_b},
        "dbRows": {"documentsA": docs_a, "documentsB": docs_b, "chunksA": chunk_rows_a},
    }
    report_path = Path(__file__).resolve().parents[1] / "test-artifacts" / "compose-smoke.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[compose-smoke] 报告 {report_path}")

    print("[compose-smoke] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
