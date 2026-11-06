"""把 P7 报告的 A 项从「等价验收」升级为「compose 实测通过」。

一次性脚本：结果写回 test-artifacts/backend-gate-P7.json。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "test-artifacts" / "backend-gate-P7.json"

data = json.loads(REPORT.read_text(encoding="utf-8"))

data["status"] = "verified"
data["blockedItems"] = []
data["passNote"] = (
    "A–G 七项全部真实取证。A 项由 docker compose（预构建镜像 + 宿主机 MySQL）实测通过："
    "三容器 healthy、Flyway 认出 v7、经 nginx 8088 登录与列表正常、tools/compose_smoke.py PASS、"
    "容器栈上根门禁 246 passed / 1 skipped、mock 档 J3+J5 55 passed、浏览器 G1–G4 PASS。"
)
data["timestamp"] = "2026-11-06T10:40:00+08:00"
data["environment"] = {
    "topology": (
        "docker compose（deploy/docker-compose.localdb-prebuilt.yml）："
        "deploy-python-ai-1 + deploy-java-backend-1 + deploy-frontend-1，"
        "数据库为宿主机 MySQL 8.0.39 (host.docker.internal:3306)，前端经 nginx 8088 暴露"
    ),
    "db": "xiaoyi_rag_local_gate (宿主机 MySQL 8.0.39)",
    "javaProfiles": "gate-probe",
    "accounts": ["local-a (id=2)", "local-b (id=3)"],
    "startScript": (
        "docker compose -f deploy/docker-compose.localdb-prebuilt.yml "
        "--env-file deploy/local-mysql.env up -d --build"
    ),
    "evidenceFiles": [
        "test-artifacts/compose-smoke.json",
        "test-artifacts/p7-browser.json",
        "test-artifacts/p7-redocly.txt",
        "test-artifacts/screenshots/p7-a-knowledge.png",
        "test-artifacts/screenshots/p7-a-chat.png",
        "test-artifacts/screenshots/p7-b-knowledge.png",
    ],
}

item_a = data["items"][0]
item_a["name"] = "Compose 起栈 healthy 且无 IllegalStateException（容器栈实测）"
item_a["status"] = "verified"
item_a["command"] = (
    "docker compose -f deploy/docker-compose.localdb-prebuilt.yml "
    "--env-file deploy/local-mysql.env up -d --build"
)
item_a["blockedBy"] = None
item_a["result"] = (
    "三容器 healthy；Flyway 认出现有 v7；经 nginx 8088 登录 200 / 列表 200 / health UP；"
    "compose_smoke.py PASS"
)
item_a["verifiedInstead"] = [
    "`docker compose ps` → deploy-python-ai-1 Up (healthy)、deploy-java-backend-1 Up (healthy)、"
    "deploy-frontend-1 Up，端口 0.0.0.0:8088->80、0.0.0.0:8080->8080",
    "java 日志 `Database: jdbc:mysql://host.docker.internal:3306/xiaoyi_rag_local_gate (MySQL 8.0)`、"
    "`Successfully validated 7 migrations`、`Current version of schema xiaoyi_rag_local_gate: 7`、"
    "`Schema is up to date. No migration necessary.` —— 容器内连的是宿主机库，Flyway 认得已有 7 个版本",
    "`Started XiaoyiRagApplication in 49.295 seconds`（冷启动 49.3s，healthcheck 的 start_period 因此设为 90s）",
    "经 nginx(8088)：`POST /api/v1/auth/login` → code=0、token 227 字符、user.id=2、username=local-a、"
    "expiresIn=3600；`GET /api/v1/documents` → count=6；`GET /api/v1/health` → UP；"
    "`GET /` → 200、715 字节、含 `<div id=\"app\">`",
    "`python tools/compose_smoke.py` → 首页 ok / 登录 ok local-a(id=2) / local-b(id=3) / 列表隔离 ok / "
    "建库 SUCCEEDED / chunks 隔离 A=1 B=0 / 库核对 db=xiaoyi_rag_local_gate / PASS",
    "容器栈上根门禁 `pytest J0-contract J1-skeleton J2-crud J4-ingest J6-integration J7-isolation -q` "
    "→ 246 passed, 1 skipped in 153.52s",
    "mock 档（另起 AI_MOCK=true 的 java 容器于 8081，同一套库与 storage 卷）`pytest J3-sse J5-eval -q` "
    "→ 55 passed in 125.62s",
    "浏览器双账号（P7_WEB_DIST=frontend/dist、P7_JAVA=127.0.0.1:8080）→ G1 PASS（A 见自己 12 份）、"
    "G3 PASS（回答 21 字 / 候选 3 段 · 采用 3 段）、G2 PASS（B 见自己 12 份）、G4 PASS（sub 2/3）、"
    "`🎉 G 项浏览器双账号联调通过`",
]
item_a["equivalentEvidence"] = (
    "compose 内 java-backend 连宿主机 MySQL 8.0.39，表结构由同一份 Flyway V1–V7 建立；"
    "前端产物经 nginx 托管并反代 /api/v1，与生产拓扑一致。"
)
item_a["note"] = (
    "基础镜像 mysql:8.0 与 maven:3.9.9-eclipse-temurin-21 在本机镜像站被限流（short read / toomanyrequests），"
    "因此 java/frontend 走 Dockerfile.runtime 直接拷宿主机已构建的 jar 与 dist，数据库用宿主机 8.0.39 —— "
    "这就是 deploy/docker-compose.localdb-prebuilt.yml 的定位。"
)
item_a["composeBlockedBy"] = (
    "不再阻断：构建期基础镜像（maven、mysql:8.0）仍不可靠，但运行期基础镜像"
    "（eclipse-temurin:21-jre、nginx:1.27-alpine、python:3.12-slim）可拉取，故用预构建镜像路径绕开。"
)

data["fixedDuringAcceptance"] += [
    "deploy/docker-compose.localdb-prebuilt.yml 的 java healthcheck 由 `exec 3<>/dev/tcp/...` 改为 "
    "`curl -fsS http://127.0.0.1:8080/api/v1/health`：eclipse-temurin:21-jre 的 /bin/sh 是 dash，"
    "不支持 bash 的 /dev/tcp，表现为 `cannot create /dev/tcp/127.0.0.1/8080: Directory nonexistent`、"
    "容器恒 unhealthy 并阻塞 frontend 启动。",
    "compose 的 java-backend 补 `SPRING_PROFILES_ACTIVE=${SPRING_PROFILES_ACTIVE:-gate-probe}`："
    "不设则 GateProbeController 不注册，J1 十条错误码用例全部 404。",
    "compose 的 java-backend 补 `STORAGE_ROOT=/app/storage` 并把 `../server-java/storage` 挂到该路径："
    "不挂卷时资料写在容器内，J2 的「磁盘上应有 server-java/storage/<id>/<name>」断言必然失败。",
    "compose 的 python-ai 补 `INGEST_STAGE_DELAY_MS`：原来只给了 java-backend，而该变量只被 "
    "server-ai/app/config.py 读取，Java 侧不读，导致 J4 的五阶段用例只看到 parsing 与 done。",
    "frontend/Dockerfile.runtime.dockerignore 新增：frontend/.dockerignore 第 2 行排除了 dist，"
    "BuildKit 会把它应用到 Dockerfile.runtime，报 `failed to compute cache key: \"/dist\": not found`。",
]

data["knownLimitations"] = [
    "构建期基础镜像 mysql:8.0 与 maven:3.9.9-eclipse-temurin-21 在本机镜像站被限流，"
    "deploy/docker-compose.yml（容器内跑 Maven + mysql 容器）未取证；实测通过的是 "
    "deploy/docker-compose.localdb-prebuilt.yml（预构建 jar/dist + 宿主机 MySQL）。",
    "J3/J5 依赖 MockAiClient 的 [fail] 标记与关键词打分，必须在 AI_MOCK=true 的 Java 实例上跑；"
    "真实 provider 下这两组失败属于运行配置不匹配，不是代码回归。容器栈里为此另起了一个 8081 的 mock 实例。",
    "Windows 系统代理（HKCU Internet Settings ProxyServer=127.0.0.1:7890）会被 httpx 读取，"
    "即使 ProxyOverride 里有 127.*；未设 NO_PROXY 时 pytest 打 127.0.0.1:8080 会得到 502（代理转不出去）。"
    "跑门禁前需 `NO_PROXY=127.0.0.1,localhost`。",
    "test-artifacts/p7-java.log 恒为 0 字节（本环境 stdout 重定向对 detach 进程不生效），"
    "排查以 tools/p7_java_fg.py 的前台日志 test-artifacts/p7-java-fg.log 为准。",
    "本机直连模式下 Python 状态库与 Java 落盘目录必须分开：J2 的 clean_storage 会清空 STORAGE_ROOT，"
    "同一目录会让 uvicorn 占住 sqlite 文件（WinError 32）。",
]

REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[update-p7] written {REPORT}")
print(f"[update-p7] status={data['status']} allItemsOk={all(i['ok'] for i in data['items'])}")
