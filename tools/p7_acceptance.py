"""P7 验收 C/D/F 三项取证脚本（B 项由 test/J7-isolation 覆盖，A/G 见文档说明）。

用法::

    python tools/p7_acceptance.py            # 跑 C + F
    python tools/p7_acceptance.py --with-d   # 额外跑 D（会重启 python，需真实 provider）

每项都记录真实请求、真实响应与判据，结果写 test-artifacts/p7-evidence.json，
供 docs/03-架构评审 的 P7 验收表引用。脚本不做断言即通过的花架子：判据不满足时
该项 `ok=false` 并带上实际值，退出码 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p7_up  # noqa: E402
from p7_env import load  # noqa: E402

BASE_JAVA = "http://127.0.0.1:8080"
BASE_AI = "http://127.0.0.1:8000"
OUT = p7_up.ARTIFACTS / "p7-evidence.json"


def http(
    method: str,
    url: str,
    token: str | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    """发一次请求并返回 (状态码, 解析后的 body)。非 JSON 响应按文本返回。"""
    data = None
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def login(username: str, password: str) -> str:
    status, payload = http(
        "POST", f"{BASE_JAVA}/api/v1/auth/login", body={"username": username, "password": password}
    )
    if status != 200 or payload.get("code") != 0:
        raise SystemExit(f"登录失败 {username}: {status} {payload}")
    return payload["data"]["token"]


def upload(token: str, name: str, text: str) -> int:
    """multipart 上传一份 md，返回 docId。"""
    boundary = "----p7" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_JAVA}/api/v1/documents",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    accepted = payload["data"]["accepted"]
    if not accepted:
        raise SystemExit(f"上传被拒：{payload}")
    return int(accepted[0]["id"])


def wait_terminal(token: str, task_id: Any, timeout: float = 90.0) -> dict[str, Any] | None:
    """轮询任务直到终态；超时返回最后一次拿到的视图。"""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        status, payload = http("GET", f"{BASE_JAVA}/api/v1/index/tasks/{task_id}", token=token)
        if status == 200:
            last = payload["data"]
            if last["status"] in ("SUCCEEDED", "FAILED"):
                return last
        time.sleep(0.3)
    return last


def drain_active_tasks(token: str, timeout: float = 120.0) -> None:
    """把该用户所有非终态任务等到终态：409 说明还有在跑的，就再探一次并等它结束。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = http(
            "POST", f"{BASE_JAVA}/api/v1/index/rebuild", token=token, body={"chunkSize": 180, "overlap": 30}
        )
        if status == 200:
            wait_terminal(token, payload["data"]["id"])
            return
        if status == 409:
            time.sleep(0.5)
            continue
        raise SystemExit(f"清理任务失败：{status} {payload}")


def check_c_concurrent_rebuild(token: str) -> dict[str, Any]:
    """C：同一用户并发两次 POST /index/rebuild，只能受理一个，另一个 409/40903。

    <p>必须先有语料：空语料的重建会立刻收成 SUCCEEDED（`finishEmptyRebuild`），
    没有非终态窗口，两个请求都会 200，验不到串行化。有语料时 Python 侧要跑完
    parsing→done 若干秒，窗口才真实存在。
    """
    drain_active_tasks(token)
    upload(token, f"p7_concurrent_{uuid.uuid4().hex[:6]}.md", "# 并发验证\n\n正文用于占住建库窗口。\n")

    def fire() -> tuple[int, Any]:
        return http(
            "POST", f"{BASE_JAVA}/api/v1/index/rebuild", token=token, body={"chunkSize": 140, "overlap": 30}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: fire(), range(2)))

    codes = sorted(r[0] for r in results)
    accepted = [r for r in results if r[0] == 200]
    rejected = [r for r in results if r[0] == 409]
    ok = (
        codes == [200, 409]
        and len(accepted) == 1
        and len(rejected) == 1
        and rejected[0][1].get("code") == 40903
    )
    accepted_id = accepted[0][1]["data"]["id"] if accepted else None
    if accepted_id is not None:
        wait_terminal(token, accepted_id)
    return {
        "item": "C",
        "name": "并发建库幂等（同一用户同时两次 rebuild）",
        "ok": ok,
        "expected": "一个 200 + 一个 409/40903，库层唯一键 uk_index_task_active_user 兜底",
        "statuses": codes,
        "acceptedTaskId": accepted_id,
        "rejected": rejected[0][1] if rejected else None,
        "note": "契约不接受客户端幂等键，并发语义是「只受理一个」而非「返回同一 task_id」；"
        "同一 submission_key 的重放复用由轮询器 triggerParse 保证。",
    }


def check_f_apidocs(token: str) -> dict[str, Any]:
    """F：springdoc 实际暴露的 /v3/api-docs 与契约 operationId 集合对得上。"""
    status, docs = http("GET", f"{BASE_JAVA}/v3/api-docs")
    paths = docs.get("paths", {}) if isinstance(docs, dict) else {}
    operation_ids = sorted(
        op["operationId"]
        for item in paths.values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    )
    contract = p7_up.REPO_ROOT / "docs" / "api" / "openapi-public.yaml"
    import yaml

    spec = yaml.safe_load(contract.read_text(encoding="utf-8"))
    contract_ids = sorted(
        op["operationId"]
        for item in spec["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    )
    missing = [i for i in contract_ids if i not in operation_ids]
    extra = [i for i in operation_ids if i not in contract_ids]
    return {
        "item": "F",
        "name": "实际 /v3/api-docs 与契约 operationId 对齐",
        "ok": status == 200 and not missing,
        "expected": "200，且契约 28 个 operationId 在实现侧都存在",
        "httpStatus": status,
        "pathCount": len(paths),
        "operationCount": len(operation_ids),
        "contractCount": len(contract_ids),
        "missingInImplementation": missing,
        "extraInImplementation": extra,
    }


def check_d_restart(token: str) -> dict[str, Any]:
    """D：python 重启后，中断任务必须 FAILED 且 error 含「服务重启导致任务中断」。"""
    pids = p7_up._read_pids()
    drain_active_tasks(token)
    doc_id = upload(token, f"p7_restart_{uuid.uuid4().hex[:6]}.md", "# 重启验证\n\n正文用于构造中断任务。\n")
    status, payload = http(
        "POST", f"{BASE_JAVA}/api/v1/index/rebuild", token=token, body={"chunkSize": 180, "overlap": 30}
    )
    if status != 200:
        return {"item": "D", "name": "重启后中断任务置 FAILED", "ok": False, "error": payload}
    task_id = payload["data"]["id"]

    # 等任务进入 RUNNING 再杀 python，确保中断发生在执行中
    for _ in range(40):
        _, one = http("GET", f"{BASE_JAVA}/api/v1/index/tasks/{task_id}", token=token)
        if one["data"]["status"] == "RUNNING":
            break
        time.sleep(0.1)

    p7_up._kill(pids.get("python"))
    time.sleep(1.0)
    env = p7_up.build_env(load())
    pids["python"] = p7_up.start_python(env)
    p7_up._write_pids(pids)
    cfg = load()
    ready = p7_up._wait(
        f"{BASE_AI}/internal/v1/health", 90.0, {"X-Internal-Token": cfg["INTERNAL_TOKEN"]}
    )

    final = wait_terminal(token, task_id, timeout=90.0)
    error = (final or {}).get("error") or ""
    return {
        "item": "D",
        "name": "python 重启后中断任务置 FAILED",
        "ok": ready and final is not None and final["status"] == "FAILED" and "服务重启导致任务中断" in error,
        "expected": "status=FAILED，error 含「服务重启导致任务中断，请重新提交解析任务」",
        "pythonRestarted": ready,
        "taskId": task_id,
        "documentId": doc_id,
        "finalStatus": (final or {}).get("status"),
        "finalError": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-d", action="store_true", help="额外跑 D（会重启 python）")
    parser.add_argument("--only", default="", help="只跑指定项，逗号分隔，如 C,F")
    args = parser.parse_args()

    cfg = load()
    token = login(cfg["AUTH_BOOTSTRAP_USERNAME"], cfg["AUTH_BOOTSTRAP_PASSWORD"])
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}

    items: list[dict[str, Any]] = []
    if not only or "C" in only:
        items.append(check_c_concurrent_rebuild(token))
        print(f"[C] ok={items[-1]['ok']} statuses={items[-1]['statuses']}", flush=True)
    if not only or "F" in only:
        items.append(check_f_apidocs(token))
        print(f"[F] ok={items[-1]['ok']} paths={items[-1]['pathCount']}", flush=True)
    if args.with_d or "D" in only:
        items.append(check_d_restart(token))
        print(f"[D] ok={items[-1]['ok']} status={items[-1].get('finalStatus')}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"generatedAt": int(time.time()), "base": BASE_JAVA, "items": items},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[p7_acceptance] 写入 {OUT}")
    return 0 if all(item["ok"] for item in items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
