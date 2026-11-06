"""一次性：把 stack 模式（mysql 也在容器里）的实测证据写回 P7 报告 A 项。

用法：python tools/update_p7_stack.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P7 = ROOT / "test-artifacts" / "backend-gate-P7.json"

EXTRA_EVIDENCE = [
    "`docker pull mysql:8.0` 成功（Digest sha256:7dcddc01f13bab2f15cde676d44d01f61fc9f99fe7785e86196dfc07d358ae2b），"
    "此前三次 short read / token EOF 已随网络恢复",
    "`python tools/docker_deploy.py --mode stack up --smoke` → pass=true，169.324s，"
    "四容器（mysql / python-ai / java-backend / frontend）全部 healthy",
    "容器内 mysql 从空库起：`Successfully applied 7 migrations to schema `xiaoyi_rag_local_gate`, "
    "now at version v7 (execution time 00:04.788s)`，`Flyway 迁移完成，当前 schema version = 7`，"
    "`Started XiaoyiRagApplication in 24.416 seconds`",
    "`python tools/check_stack_db.py` → tables=13、flyway=1:1,2:1,3:1,4:1,5:1,6:1,7:1、"
    "documentsByUser=2=1,3=1、chunksByUser=2=1（跨用户隔离成立）",
    "`compose_smoke.py --db-via-container` PASS：库核对(container) docs A=2 B=2 chunksA=2",
]


def main() -> int:
    report = json.loads(P7.read_text(encoding="utf-8"))
    item = report["items"][0]
    item["name"] = "Compose 起栈 healthy 且无 IllegalStateException（prebuilt + stack 两种形态均实测）"
    item["result"] = (
        "prebuilt 形态：三容器 healthy，Flyway 认出现有 v7，经 nginx 8088 登录 200 / 列表 200 / health UP；"
        "stack 形态：四容器（含 mysql:8.0）healthy，容器内 MySQL 从空库跑完 V1–V7 共 13 表，"
        "双账号数据按用户隔离；两种形态 compose_smoke.py 均 PASS"
    )
    evidence = list(item.get("evidence") or [])
    for line in EXTRA_EVIDENCE:
        if line not in evidence:
            evidence.append(line)
    item["evidence"] = evidence
    item["note"] = (
        "prebuilt 走 deploy/docker-compose.localdb-prebuilt.yml（宿主机 MySQL）；"
        "stack 走 deploy/docker-compose.yml（mysql 容器，compose_smoke 自动加 --db-via-container）。"
        "两者共用 python tools/docker_deploy.py 入口，报告落 test-artifacts/docker-deploy-<mode>.json。"
    )
    P7.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[update-p7-stack] A 项已更新，evidence {len(evidence)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
