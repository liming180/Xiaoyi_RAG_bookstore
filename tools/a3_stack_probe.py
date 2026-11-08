"""A3 容器栈端到端探针：真实 embedding + Milvus + 四档检索。

验证的是「容器里跑的那套」而不是进程内 TestClient：
Python 容器读的是 compose 注入的 RETRIEVAL_MODE=hybrid，Milvus 是 xi-milvus，
embedding 打的是智谱。走 Java 公开 API（登录 → 上传 → 建库 → SSE），
检索结果只能从 SSE 的 retrieval 帧拿 —— Java 没有独立的 retrieve 端点。

用法（仓库根，需三端容器 healthy）：
    python tools/a3_stack_probe.py

与 `tools/a3_compare.py` 的分工：`a3_compare.py` 在进程内用 TestClient 比四档指标；
这个脚本打的是 8080 上真正跑着的容器栈（compose 注入的 RETRIEVAL_MODE），
验的是「部署形态下 A3 是否真的在跑」，两者缺一不可。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8080"
DATA = ROOT / "assets" / "data"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / "deploy" / "local-mysql.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def login(username: str, password: str) -> tuple[str, int]:
    status, payload = call("POST", "/api/v1/auth/login", body={"username": username, "password": password})
    assert status == 200, (status, payload)
    data = payload["data"]
    return data["token"], int(data["user"]["id"])


def upload(token: str, path: Path) -> str:
    """multipart 字段名必须是 files（与前端 knowledge.ts、Java @RequestPart 一致）。"""
    content = path.read_bytes()
    boundary = "----a3probe"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: text/markdown\r\n\r\n".encode() + content + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(f"{BASE}/api/v1/documents", data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    assert payload["code"] == 0, payload
    data = payload["data"]
    assert not data.get("skipped"), f"文件被拒：{data['skipped']}"
    return str(data["accepted"][0]["id"])


def rebuild(token: str) -> dict:
    status, payload = call("POST", "/api/v1/index/rebuild", token, {"chunkSize": 180, "overlap": 30})
    assert status == 200 and payload["code"] == 0, (status, payload)
    task_id = payload["data"]["id"]
    deadline = time.time() + 240
    while time.time() < deadline:
        _, task = call("GET", f"/api/v1/index/tasks/{task_id}", token)
        data = task["data"]
        if data["status"] in ("SUCCEEDED", "FAILED"):
            return data
        time.sleep(1.0)
    raise TimeoutError(f"建库任务 {task_id} 240s 未到终态")


def stream(token: str, question: str, k: int = 3) -> dict:
    """解析 SSE：收集 status / retrieval / token / done 四类帧。"""
    body = json.dumps({"question": question, "mode": "rag", "k": k}).encode()
    req = urllib.request.Request(f"{BASE}/api/v1/chat/stream", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    req.add_header("Authorization", f"Bearer {token}")

    statuses: list[str] = []
    citations: list[dict] = []
    answer = ""
    done: dict = {}
    event = None
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if event == "status":
                    statuses.append(payload.get("stage", ""))
                elif event == "retrieval":
                    citations = payload.get("citations", [])
                elif event == "token":
                    answer += payload.get("content", "")
                elif event == "done":
                    done = payload
    return {"statuses": statuses, "citations": citations, "answer": answer, "done": done}


def main() -> int:
    env = load_env()
    token_a, id_a = login(env["AUTH_BOOTSTRAP_USERNAME"], env["AUTH_BOOTSTRAP_PASSWORD"])
    token_b, id_b = login(env["AUTH_SECONDARY_BOOTSTRAP_USERNAME"], env["AUTH_SECONDARY_BOOTSTRAP_PASSWORD"])
    print(f"[1] 登录 ok A={env['AUTH_BOOTSTRAP_USERNAME']}({id_a}) B={env['AUTH_SECONDARY_BOOTSTRAP_USERNAME']}({id_b})")

    docs = []
    for name in ["02_借阅规则.md", "03_空间预约.md", "05_活动调整通知.md"]:
        docs.append(upload(token_a, DATA / name))
    print(f"[2] A 上传 3 份，doc id = {docs}")

    task = rebuild(token_a)
    print(f"[3] 建库 {task['status']} chunks={task.get('chunkCount')} task={task.get('id')}")
    assert task["status"] == "SUCCEEDED", task

    result = stream(token_a, "普通图书最多借几本，借期多久？", k=3)
    print(f"[4] 阶段序列：{' → '.join(result['statuses'])}")
    print(f"[5] 检索 {len(result['citations'])} 条引用：")
    for item in result["citations"]:
        print(f"      {item['chunkId']} score={item['score']:.4f} stage={item['stage']} doc={item['docTitle']}")
    print(f"[6] SSE 回答 {len(result['answer'])} 字：{result['answer']!r}")
    print(f"    done: degraded={result['done'].get('degraded')} messageId={result['done'].get('messageId')}")

    cross = stream(token_b, "普通图书最多借几本，借期多久？", k=3)
    print(f"[7] 跨用户：B 检索到 {len(cross['citations'])} 条引用，回答 {len(cross['answer'])} 字")
    assert not cross["citations"], "跨用户串数据"

    trace_status, trace = call("GET", f"/api/v1/messages/{result['done']['messageId']}/trace", token_a)
    rows = trace["data"]["rows"] if trace_status == 200 else []
    print(f"[8] 轨迹 {len(rows)} 行，retrieved={[row['retrieved'] for row in rows]}")
    assert len(rows) >= len(result["citations"]), "轨迹行数应不少于引用数（含淘汰区）"

    ok = (
        len(result["citations"]) > 0
        and result["answer"]
        and not cross["citations"]
        and len(rows) >= len(result["citations"])
    )
    print("\nPASS —— 容器栈走的是 A3 混合检索（BM25 + RRF + 可降级重排）" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
