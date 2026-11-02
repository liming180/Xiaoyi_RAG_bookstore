"""启动 Java 服务并等到健康检查通过，供 J1 及后续阶段复用。

用法::

    py -3.12 -X utf8 test/scripts/serve_java.py                      # 前台跑，Ctrl-C 退出
    py -3.12 -X utf8 test/scripts/serve_java.py --profile gate-probe # 带门禁探针（J1 门禁用）
    py -3.12 -X utf8 test/scripts/serve_java.py --detach             # 后台跑，打印 pid

为什么不直接 `java -jar`：Spring Boot 启动 + Flyway 迁移要十几秒，测试脚本需要
「等到能打」再开跑，避免用 sleep 硬等。

关于 `--profile gate-probe`：手册 §5 的 J1 测试要求造 400 / 401 / 409 / 503 四类，
但 J1 骨架里没有任何真实业务能产生 409 / 503（实验并发、建库任务并发、AI 不可用
都要等 J4 / J6）。`GateProbeController` 只在 `gate-probe` profile 下注册
`GET /__gate/throw?code=NNNNN`，让黑盒测试真走一遍 `GlobalExceptionHandler`。

关于数据库：J1 需要「MySQL 里能看到 7 张表」。连本机 MySQL80（3306）的
`xiaoyi_rag` 库即可，口令从用户级环境变量 `MYSQL_PASSWORD` 读，仓库里不出现明文。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "server-java"
JAR = SERVER_DIR / "target" / "xiaoyi-rag-server-0.1.0-SNAPSHOT.jar"
BASE_JAVA = os.getenv("BASE_JAVA", "http://127.0.0.1:8080")

DEFAULT_DB_PORT = os.getenv("DB_PORT", "3306")
DEFAULT_DB_NAME = os.getenv("MYSQL_DATABASE", "xiaoyi_rag")


def env_or_user_registry(name: str, default: str = "") -> str:
    """先读进程环境变量，读不到再回落到 Windows「用户变量」（注册表 HKCU\\Environment）。

    本机口令放在用户级 `MYSQL_PASSWORD` 里，而已经开着的终端不会自动继承新设的
    用户变量，所以这里补一条回落路径，避免为了跑门禁还要重启 IDE / 终端。
    """
    value = os.getenv(name)
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            return default
    return default


def wait_health(timeout: float = 90.0) -> bool:
    """轮询 /api/v1/health，直到 200 或超时。"""
    deadline = time.monotonic() + timeout
    url = f"{BASE_JAVA}/api/v1/health"
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = repr(exc)
        time.sleep(0.5)
    print(f"[serve_java] 健康检查超时：{last}", file=sys.stderr)
    return False


def build_cmd(profile: str | None, port: str, db_port: str, db_name: str) -> list[str]:
    """拼 java 启动命令；DB 相关一律走 -D 系统属性覆盖 application.yml。"""
    url = (
        f"jdbc:mysql://127.0.0.1:{db_port}/{db_name}"
        "?useSSL=false&serverTimezone=Asia/Shanghai"
        "&characterEncoding=utf8&allowPublicKeyRetrieval=true"
    )
    cmd = [
        "java",
        f"-Dspring.datasource.url={url}",
        f"-Dspring.datasource.username={env_or_user_registry('MYSQL_USER', 'root')}",
        f"-Dspring.datasource.password={env_or_user_registry('MYSQL_PASSWORD')}",
        "-jar",
        str(JAR),
        f"--server.port={port}",
    ]
    if profile:
        cmd.append(f"--spring.profiles.active={profile}")
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detach", action="store_true", help="后台启动，打印 pid 后退出")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--profile",
        default=None,
        help="Spring profile，J1 门禁传 gate-probe 以注册 /__gate/throw 探针",
    )
    parser.add_argument(
        "--db-port",
        default=DEFAULT_DB_PORT,
        help=f"MySQL 端口，默认 {DEFAULT_DB_PORT}（本机 MySQL80）",
    )
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument(
        "--log",
        default=str(REPO_ROOT / "test-artifacts" / "java-run.out.log"),
    )
    args = parser.parse_args()

    if not JAR.exists():
        print(f"[serve_java] 找不到 jar：{JAR}，先跑 mvn -DskipTests package", file=sys.stderr)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    creationflags = 0
    if sys.platform == "win32":
        # 关键：脱离当前控制台/作业对象，否则父进程退出会把 java 一起带走。
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    cmd = build_cmd(
        args.profile,
        BASE_JAVA.rsplit(":", 1)[-1],
        args.db_port,
        args.db_name,
    )
    print(f"[serve_java] {' '.join(cmd)}")

    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=str(SERVER_DIR),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )

    print(f"[serve_java] pid={proc.pid} log={log_path}")

    if not wait_health(args.timeout):
        return 1

    print(f"[serve_java] 健康检查通过：{BASE_JAVA}/api/v1/health")

    if args.detach:
        Path(REPO_ROOT / "test-artifacts" / "java.pid").write_text(str(proc.pid), encoding="utf-8")
        return 0

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
