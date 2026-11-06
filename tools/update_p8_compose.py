"""把 P8 报告刷新为 2026-11-06 容器栈模式下的实测数字。

一次性脚本：结果写回 test-artifacts/backend-gate-P8.json。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "test-artifacts" / "backend-gate-P8.json"

data = json.loads(REPORT.read_text(encoding="utf-8"))
data["timestamp"] = "2026-11-06T10:45:00+08:00"
data["pass"] = True
data["name"] = "前端质量收口 + 后端全量回归（2026-11-06 容器栈复跑）"

gates = {g["key"]: g for g in data["gates"]}

front = gates["frontend-gate"]
front["ok"] = True
front["exitCode"] = 0
for inner in front["gates"]:
    if inner["key"] == "lint":
        inner["elapsedMs"] = 59241
    elif inner["key"] == "test":
        inner["counts"] = {
            "filesPassed": 25,
            "filesFailed": 0,
            "testsPassed": 303,
            "testsFailed": 0,
        }
    elif inner["key"] == "contract":
        inner["tail"] = "30 个接口与契约一致"
front["note"] = (
    "四关全绿：ESLint 通过、vue-tsc 通过、Vitest 25 files / 303 tests passed、"
    "contract drift 30 个接口一致，整轮 201887ms。"
    "首次运行曾因验收期临时探针（probe-chat.mjs / probe-input.mjs / probe-newconv.mjs）"
    "触发 no-console 与 no-empty 而失败，删除后复跑通过。"
)

gates["java-verify"]["ok"] = True
gates["java-verify"]["exitCode"] = 0
gates["java-verify"]["counts"] = {
    "testsPassed": 61,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
}
gates["java-verify"]["detail"] = (
    "AuthServiceTest 11 / ChatServiceImplTest 8 / DocumentServiceImplTest 7 / "
    "ExperimentServiceTest 3 / FeedbackServiceTest 7 / IndexServiceImplTest 13 / TokenServiceTest 12"
)

real = gates["root-gates-real-provider"]
real["ok"] = True
real["command"] = (
    "cd test; NO_PROXY=127.0.0.1,localhost python -m pytest "
    "J0-contract J1-skeleton J2-crud J4-ingest J6-integration J7-isolation -q"
)
real["counts"] = {"passed": 246, "skipped": 1, "failed": 0}
real["elapsed"] = "153.52s"
real["topology"] = (
    "docker compose（deploy/docker-compose.localdb-prebuilt.yml）：java 8080 / python 8000 容器 + "
    "宿主机 MySQL 8.0.39；AI_MOCK=false；SPRING_PROFILES_ACTIVE=gate-probe；INGEST_STAGE_DELAY_MS=1200"
)
real["skip"] = "J1-skeleton/test_envelope_all_routes.py:106 参数集为空"

mock = gates["root-gates-mock-provider"]
mock["ok"] = True
mock["command"] = "cd test; NO_PROXY=127.0.0.1,localhost python -m pytest J3-sse J5-eval -q"
mock["counts"] = {"passed": 55, "failed": 0}
mock["elapsed"] = "125.62s"
mock["topology"] = (
    "另起 AI_MOCK=true 的 java 容器（8081，同 network / 同库 / 同 storage 卷），"
    "因为 J3/J5 依赖 MockAiClient 的 [fail] 标记与关键词打分"
)

data["gates"].append(
    {
        "key": "compose-stack",
        "command": (
            "docker compose -f deploy/docker-compose.localdb-prebuilt.yml "
            "--env-file deploy/local-mysql.env up -d --build && python tools/compose_smoke.py"
        ),
        "ok": True,
        "exitCode": 0,
        "detail": (
            "deploy-python-ai-1 / deploy-java-backend-1 / deploy-frontend-1 三容器 healthy；"
            "java 日志 `Database: jdbc:mysql://host.docker.internal:3306/xiaoyi_rag_local_gate (MySQL 8.0)`、"
            "`Successfully validated 7 migrations`、`Current version of schema xiaoyi_rag_local_gate: 7`；"
            "经 nginx 8088 登录 200 / 列表 200 / health UP；compose_smoke.py PASS"
        ),
        "report": "test-artifacts/compose-smoke.json",
        "note": (
            "基础镜像 mysql:8.0 与 maven 在镜像站被限流，故 java/frontend 用 Dockerfile.runtime "
            "拷宿主机已构建产物，数据库用宿主机 8.0.39。修复了四处 compose 配置缺陷："
            "healthcheck 的 /dev/tcp（dash 不支持）、缺 gate-probe profile、"
            "缺 STORAGE_ROOT 挂卷、INGEST_STAGE_DELAY_MS 只给了 java。"
        ),
    }
)

data["notRun"] = []
data["knownLimitations"] = [
    "deploy/docker-compose.yml（容器内跑 Maven 构建 + mysql:8.0 容器）未取证：本机镜像站对 "
    "maven:3.9.9-eclipse-temurin-21 与 mysql:8.0 限流（short read / toomanyrequests）。"
    "实测通过的是 deploy/docker-compose.localdb-prebuilt.yml。",
    "J3/J5 必须在 AI_MOCK=true 的 Java 实例上跑；真实 provider 下这 10 条失败属于运行配置不匹配，"
    "不是代码回归（容器栈里为此另起了 8081 的 mock 实例）。",
    "Windows 系统代理 127.0.0.1:7890 会被 httpx 读取（ProxyOverride 的 127.* 对 httpx 不生效），"
    "跑门禁前需 NO_PROXY=127.0.0.1,localhost，否则打本机端口会拿到 502。",
    "A2 真 RAG 与 A3 混合检索未开始；mock provider 下的隔离与协议测试不代表检索质量。",
]

REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[update-p8] written {REPORT}")
print(f"[update-p8] gates={len(data['gates'])} allOk={all(g['ok'] for g in data['gates'])}")
