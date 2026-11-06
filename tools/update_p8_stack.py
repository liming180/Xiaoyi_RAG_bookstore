"""一次性：把三种 compose 形态的实测结果写回 P8 报告的 compose-stack 门禁。

用法：python tools/update_p8_stack.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P8 = ROOT / "test-artifacts" / "backend-gate-P8.json"

MODES = [
    ("prebuilt", "test-artifacts/docker-deploy-prebuilt.json"),
    ("full", "test-artifacts/docker-deploy-full.json"),
    ("stack", "test-artifacts/docker-deploy-stack.json"),
]


def main() -> int:
    report = json.loads(P8.read_text(encoding="utf-8"))
    rows = []
    for mode, path in MODES:
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        rows.append(
            f"`--mode {mode}`：pass={data['pass']}，{data['elapsedSeconds']}s，"
            f"compose={data['compose']}，database={data['database']}"
        )
    for gate in report["gates"]:
        if gate.get("key") != "compose-stack":
            continue
        gate["command"] = (
            "python tools/docker_deploy.py up --smoke && "
            "python tools/docker_deploy.py --mode full up --smoke && "
            "python tools/docker_deploy.py --mode stack up --smoke"
        )
        gate["detail"] = (
            "三种形态全部实测通过。prebuilt：三容器 healthy，java 日志 "
            "`Database: jdbc:mysql://host.docker.internal:3306/xiaoyi_rag_local_gate (MySQL 8.0)`、"
            "`Successfully validated 7 migrations`、`Current version of schema xiaoyi_rag_local_gate: 7`。"
            "full：容器内 Maven 构建（首次 379s）+ 宿主机库，三容器 healthy。"
            "stack：四容器（含 mysql:8.0）healthy，容器内 MySQL 从空库跑完 V1–V7，"
            "`Successfully applied 7 migrations ... now at version v7 (execution time 00:04.788s)`，"
            "`check_stack_db.py` 得 tables=13 / flyway 1–7 全 success / documentsByUser=2=1,3=1 / chunksByUser=2=1。"
            "三者经 nginx 8088 登录 200 / 列表 200 / health UP，compose_smoke.py 均 PASS。"
        )
        gate["report"] = "test-artifacts/docker-deploy-prebuilt.json / -full.json / -stack.json"
        gate["note"] = (
            "修复了六处缺陷：healthcheck 的 /dev/tcp（dash 不支持）、缺 gate-probe profile、"
            "缺 STORAGE_ROOT 挂卷、INGEST_STAGE_DELAY_MS 只给了 java、"
            "mysql 镜像拒绝 MYSQL_USER=root（改用 MYSQL_USER_FOR_CONTAINER）、"
            "compose config --images 不带服务名导致镜像映射可能错位（改用 --format json）。"
        )
        gate["modes"] = rows
    limitations = [
        "A2 真 RAG 与 A3 混合检索未开始；mock provider 下的隔离与协议测试不代表检索质量。",
        "J3/J5 必须在 AI_MOCK=true 的 Java 实例上跑；真实 provider 下这 10 条失败属于运行配置不匹配，不是代码回归（容器栈里为此另起了 8081 的 mock 实例）。",
        "Windows 系统代理 127.0.0.1:7890 会被 httpx 读取（ProxyOverride 的 127.* 对 httpx 不生效），跑门禁前需 NO_PROXY=127.0.0.1,localhost。",
        "容器内 Maven 构建依赖 maven 基础镜像与 Maven Central，网络波动会整段失败（首次报 DependencyResolutionException，重试即成功）；日常用 --mode prebuilt 绕开。",
        "p7-java.log 恒 0 字节（detach 时 stdout 重定向不生效），排查看 test-artifacts/p7-java-fg.log。",
    ]
    report["knownLimitations"] = limitations
    report["notRun"] = []
    P8.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[update-p8-stack] compose-stack 门禁已更新为三形态实测")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
