"""三份 compose 的统一入口：日常预构建，以及网络/CI 就绪后的完整镜像构建。

三种形态（--mode，默认 prebuilt）：

    prebuilt  deploy/docker-compose.localdb-prebuilt.yml  宿主机 MySQL + 拷宿主机 jar/dist（最快，日常用）
    full      deploy/docker-compose.localdb.yml           宿主机 MySQL + 容器内 Maven/npm 构建
    stack     deploy/docker-compose.yml                   容器内构建 + mysql:8.0 容器（交付形态）

常用：

    python tools/docker_deploy.py --prepare-db up --smoke
    python tools/docker_deploy.py --skip-host-build up --smoke
    python tools/docker_deploy.py --mode full up --smoke
    python tools/docker_deploy.py --mode stack up --smoke
    python tools/docker_deploy.py status | logs | down

prebuilt 会先跑源码验证（mvn verify + 前端 gate --build），再打包运行环境；
full/stack 强制容器内构建，不接受 --skip-host-build。up 起栈后会等容器就绪、
探首页与 Java 健康（--no-verify 可跳过），--smoke 再跑端到端冒烟。

push 只做 tag + push + 校验远端 digest，不会启动容器栈：

    $env:IMAGE_REGISTRY='registry.example.com/team'; $env:IMAGE_TAG='v1.0.0'
    python tools/docker_deploy.py --mode full build --push

报告落 test-artifacts/docker-deploy-<mode>.json。MySQL 密码、JWT 密钥等只读配置，
不写报告。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deploy" / "local-mysql.env"
ARTIFACTS = ROOT / "test-artifacts"
CONFIGS = {
    "prebuilt": ROOT / "deploy" / "docker-compose.localdb-prebuilt.yml",
    "full": ROOT / "deploy" / "docker-compose.localdb.yml",
    "stack": ROOT / "deploy" / "docker-compose.yml",
}
DATABASES = {"prebuilt": "host-mysql", "full": "host-mysql", "stack": "container-mysql"}
SERVICES = ("python-ai", "java-backend", "frontend")


def output(result: subprocess.CompletedProcess[str]) -> str:
    return ((result.stdout or "") + (result.stderr or "")).strip()


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: float | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"[docker-deploy] $ {' '.join(command)}", flush=True)
    result = subprocess.run(
        resolve_executable(command),
        cwd=cwd,
        env=os.environ.copy(),
        shell=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = output(result)
        if detail:
            print(detail, file=sys.stderr, flush=True)
        raise RuntimeError(f"命令失败（exit {result.returncode}）：{' '.join(command)}")
    return result


def resolve_executable(command: list[str]) -> list[str]:
    """Windows 上 mvn / npm 实际是 mvn.cmd / npm.cmd，shell=False 找不到裸名。

    注意 shutil.which('mvn') 会先命中 Maven 自带的无扩展名 shell 脚本，
    CreateProcess 跑不了它；所以命中无后缀路径时要按 PATHEXT 再找一遍。
    只解析第一个元素（可执行文件），其余参数原样保留。
    """
    if not command:
        return command
    head = command[0]
    if Path(head).is_absolute() or os.sep in head or "/" in head:
        return command
    found = shutil.which(head)
    if found and not Path(found).suffix:
        for ext in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep):
            candidate = Path(found + ext.strip().lower())
            if candidate.is_file():
                found = str(candidate)
                break
            candidate = Path(found + ext.strip().upper())
            if candidate.is_file():
                found = str(candidate)
                break
    if found:
        return [found, *command[1:]]
    return command


def checked_output(command: list[str], *, cwd: Path = ROOT) -> str:
    return (run(command, cwd=cwd, capture=True).stdout or "").strip()


def compose(args: argparse.Namespace, *parts: str, capture: bool = False):
    return run(
        ["docker", "compose", "-f", str(CONFIGS[args.mode]), "--env-file", str(ENV_FILE), *parts],
        capture=capture,
        timeout=120 if parts[:1] == ("ps",) else None,
    )


def require_inputs(args: argparse.Namespace) -> None:
    import local_mysql as mysql

    for name in ("docker", "mvn", "npm"):
        if args.skip_host_build and name in ("mvn", "npm"):
            continue
        if shutil.which(name) is None:
            raise RuntimeError(f"PATH 中找不到 {name}，请先安装并重新打开终端")
    if not ENV_FILE.is_file():
        raise RuntimeError("缺少 deploy/local-mysql.env；复制同目录 .example 后填入实际配置")
    cfg = mysql.config(ENV_FILE)
    mysql.validate(cfg, require_accounts=True)
    run(["docker", "version", "--format", "{{.Server.Version}}"], capture=True)
    compose(args, "config", "--quiet", capture=True)
    if args.push and not args.registry:
        raise RuntimeError("--push 需要 --registry 或 IMAGE_REGISTRY=registry.example.com/team")
    if args.registry and not re.fullmatch(r"[A-Za-z0-9._:/-]+", args.registry):
        raise RuntimeError("镜像仓库只能含 registry/namespace 路径字符，不能带 tag 或 digest")
    if args.mode == "stack" and not (os.getenv("MYSQL_ROOT_PASSWORD") or mysql.load_env_file(ENV_FILE).get("MYSQL_ROOT_PASSWORD")):
        raise RuntimeError("stack 模式需要 MYSQL_ROOT_PASSWORD（mysql 容器初始化用）；写进 deploy/local-mysql.env 或当前环境变量")


def host_build() -> dict[str, Any]:
    # mvn verify 同时跑单测与 Spotless；前端 gate --build 含 lint/typecheck/test/
    # 契约漂移 + vite build，产出 frontend/dist。两者在 Windows 上是 .cmd，
    # run() 里的 resolve_executable 会换成绝对路径。
    run(["mvn", "verify"], cwd=ROOT / "server-java")
    run(["npm", "run", "gate", "--", "prebuilt", "--build"], cwd=ROOT / "frontend")
    pom = (ROOT / "server-java" / "pom.xml").read_text(encoding="utf-8")
    version = re.search(r"<artifactId>xiaoyi-rag-server</artifactId>\s*<version>([^<]+)</version>", pom)
    if version is None:
        raise RuntimeError("未能从 server-java/pom.xml 读取 jar 版本")
    jar = ROOT / "server-java" / "target" / f"xiaoyi-rag-server-{version.group(1)}.jar"
    if not jar.is_file() or not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError("构建结束但 jar 或 frontend/dist/index.html 不存在")
    return {"javaJar": str(jar.relative_to(ROOT)), "frontendDist": "frontend/dist"}


def images(args: argparse.Namespace) -> dict[str, str]:
    # 不能用 `compose config --images`：它只吐镜像名字符串、不带服务名，
    # 实测顺序会错位（曾出现整体旋转一位），push 就会把前端镜像推到 java 的仓库名上。
    # 改用 config --format json 按服务名取值；没有显式 image: 的按 compose
    # 默认命名 <project>-<service> 推导，再逐个用 docker image inspect 核实。
    raw = checked_output([*compose_prefix(args), "config", "--format", "json"])
    config = json.loads(raw)
    project = str(config.get("name") or "deploy")
    mapping: dict[str, str] = {}
    for service in SERVICES:
        spec = (config.get("services") or {}).get(service) or {}
        explicit = str(spec.get("image") or "").strip()
        candidate = explicit or f"{project}-{service}"
        if run(["docker", "image", "inspect", candidate, "--format", "{{.Id}}"], capture=True, check=False).returncode != 0:
            candidate = existing_image(args, service)
        mapping[service] = candidate
    return mapping


def compose_prefix(args: argparse.Namespace) -> list[str]:
    return ["docker", "compose", "-f", str(CONFIGS[args.mode]), "--env-file", str(ENV_FILE)]


def existing_image(args: argparse.Namespace, service: str) -> str:
    # push 动作不要求重新运行 compose；按 build 阶段记录到容器上的镜像名，
    # 或当前项目的标准镜像名取实际本地镜像。
    for row in service_states(args):
        if row.get("Service") == service and row.get("Image"):
            return str(row["Image"])
    candidate = f"deploy-{service}:latest"
    result = run(["docker", "image", "inspect", candidate, "--format", "{{.Id}}"], capture=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"本地没有 {candidate}，请先执行 build 或 up")
    return candidate


def service_states(args: argparse.Namespace) -> list[dict[str, Any]]:
    result = compose(args, "ps", "--all", "--format", "json", capture=True)
    text = (result.stdout or "").strip()
    if not text:
        return []
    # Compose 版本不同可能输出 JSON 数组，也可能每行一个对象。
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def wait_healthy(args: argparse.Namespace, timeout: int) -> list[dict[str, Any]]:
    import time

    deadline = time.monotonic() + timeout
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = service_states(args)
        health = {
            row.get("Service"): (row.get("Health") or row.get("State") or "unknown").lower()
            for row in last
        }
        if all(health.get(name) == "healthy" for name in ("python-ai", "java-backend")):
            if any(row.get("Service") == "frontend" and row.get("State") == "running" for row in last):
                return last
        time.sleep(3)
    raise RuntimeError(f"容器在 {timeout}s 内未全部就绪：{json.dumps(last, ensure_ascii=False)}")


def verify(args: argparse.Namespace, timeout: int) -> dict[str, Any]:
    base = f"http://127.0.0.1:{os.getenv('FRONTEND_PORT', '8088')}"
    java = f"http://127.0.0.1:{os.getenv('JAVA_PORT', '8080')}"
    # 与 pytest 相同，禁止 Windows 注册表代理接管本机 HTTP 探测。
    probe = (
        "import json,urllib.request;"
        f"u='{base}/';h=urllib.request.urlopen(u,timeout=10);"
        "b=h.read().decode();assert h.status==200 and '<div id=\"app\"' in b;"
        f"r=urllib.request.urlopen('{java}/api/v1/health',timeout=10);"
        "d=json.load(r);assert r.status==200 and d.get('data',{}).get('status')=='UP';"
        "print(json.dumps({'homepage':'UP','javaHealth':'UP'},ensure_ascii=False))"
    )
    old_proxy, old_proxy_lower = os.environ.get("NO_PROXY"), os.environ.get("no_proxy")
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    try:
        result = run([sys.executable, "-c", probe], capture=True)
        states = wait_healthy(args, timeout)
    finally:
        for key, previous in (("NO_PROXY", old_proxy), ("no_proxy", old_proxy_lower)):
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
    return {"http": json.loads((result.stdout or "").strip()), "containers": states}


def push(args: argparse.Namespace, image_map: dict[str, str]) -> list[dict[str, str]]:
    if not args.push:
        return []
    prefix = args.registry.rstrip("/")
    pushed: list[dict[str, str]] = []
    for service, local in image_map.items():
        remote = f"{prefix}/xiaoyi-{service}:{args.tag}"
        run(["docker", "tag", local, remote])
        run(["docker", "push", remote], timeout=args.push_timeout)
        digest = checked_output([
            "docker", "buildx", "imagetools", "inspect", remote,
            "--format", "{{.Manifest.Digest}}",
        ]).strip().strip('"').strip("'")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise RuntimeError(f"推送后未读到 {remote} 的 registry digest：{digest}")
        pushed.append({"service": service, "localImage": local, "remoteImage": remote, "registryDigest": digest})
    return pushed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "status", "logs", "down", "build", "push"), nargs="?", default="up")
    parser.add_argument("--mode", choices=tuple(CONFIGS), default="prebuilt")
    parser.add_argument("--prepare-db", action="store_true", help="准备宿主机空库与容器专用 MySQL 账号，不建表（stack 模式不适用）")
    parser.add_argument("--skip-host-build", action="store_true", help="复用当前 jar/dist，只在预构建模式可用")
    parser.add_argument("--no-verify", action="store_true", help="跳过 up 之后的三容器就绪与首页/健康探测")
    parser.add_argument("--smoke", action="store_true", help="执行 compose_smoke.py：写入两份 A/B 验收资料")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--push-timeout", type=int, default=1800)
    parser.add_argument("--push", action="store_true", help="把三个镜像打 tag 并推送到 --registry")
    parser.add_argument("--registry", default=os.getenv("IMAGE_REGISTRY", ""), help="例如 registry.example.com/team，不含镜像名")
    parser.add_argument("--tag", default=os.getenv("IMAGE_TAG", "local"))
    args = parser.parse_args()
    if args.mode == "full" and args.skip_host_build:
        parser.error("full 模式强制容器内构建，不能使用 --skip-host-build")
    if args.mode == "stack" and args.prepare_db:
        parser.error("stack 模式的 MySQL 由镜像初始化，不需要 --prepare-db")
    if args.mode == "stack" and args.skip_host_build:
        parser.error("stack 模式在容器内构建，不能使用 --skip-host-build")
    if args.action == "push" and not args.push:
        parser.error("push 动作必须同时给 --push 与 --registry（或 IMAGE_REGISTRY）")
    if args.push and args.action in ("status", "logs", "down"):
        parser.error("status/logs/down 不推送镜像，请使用 build/up/push")
    if not args.tag or any(c.isspace() for c in args.tag) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", args.tag):
        parser.error("--tag 必须是合法 Docker tag")
    if args.timeout < 30 or args.push_timeout < 30:
        parser.error("超时至少 30 秒")
    return args


def main() -> int:
    args = parse_args()
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "timestamp": started.isoformat(),
        "mode": args.mode,
        "action": args.action,
        "compose": str(CONFIGS[args.mode].relative_to(ROOT)),
        "database": DATABASES[args.mode],
        "registryPushRequested": args.push,
        "hostBuildSkipped": args.skip_host_build,
        "pass": False,
    }
    try:
        require_inputs(args)
        if args.action in ("status", "logs", "down"):
            if args.action == "status":
                states = service_states(args)
                print(json.dumps(states, ensure_ascii=False, indent=2))
                report["containers"] = states
            elif args.action == "logs":
                compose(args, "logs", "--tail", "100")
            else:
                # 不带 -v：保留 Python 状态卷与数据库。
                compose(args, "down", "--remove-orphans")
            report["pass"] = True
        else:
            if args.prepare_db:
                import local_mysql as mysql

                mysql.prepare(mysql.config(ENV_FILE))
                run([sys.executable, "tools/local_mysql_grant_container.py"])
            if args.action != "push":
                if args.mode == "prebuilt" and not args.skip_host_build:
                    report["hostBuild"] = host_build()
                compose(args, "build")
            image_map = images(args)
            report["images"] = image_map
            if args.action == "up":
                compose(args, "up", "-d", "--no-build")
                if not args.no_verify:
                    report["verification"] = verify(args, args.timeout)
                if args.smoke:
                    smoke = [sys.executable, "tools/compose_smoke.py"]
                    if args.mode == "stack":
                        smoke.append("--db-via-container")
                    run(smoke)
                    report["smokeReport"] = "test-artifacts/compose-smoke.json"
            report["pushedImages"] = push(args, image_map)
            report["pass"] = True
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        report["error"] = str(exc)
        print(f"[docker-deploy] FAILED: {exc}", file=sys.stderr)
    report["elapsedSeconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
    ARTIFACTS.mkdir(exist_ok=True)
    path = ARTIFACTS / f"docker-deploy-{args.mode}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[docker-deploy] {'PASS' if report['pass'] else 'FAIL'}；报告 {path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
