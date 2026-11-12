"""P7 真实验收的服务编排：起 MySQL 之上的 Python AI + Java 后端，等到两个健康检查都通过。

用法::

    python scripts/p7_up.py            # 起服务（已起则复用），打印 pid 与健康状态
    python scripts/p7_up.py --restart-python   # 只重启 Python（用于 D 项「重启后任务 FAILED」）

为什么不用 docker compose：本机 Docker Hub 被阻断（见 P7 报告），mysql:8.0 镜像拉不下来。
这里直连本机 MySQL80 + 直起 uvicorn + jar，等价于 compose 里三个服务的拓扑，
差异只在「容器网络 → 127.0.0.1」。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p7_env import REPO_ROOT, load  # noqa: E402

JAVA_JAR = REPO_ROOT / "services" / "java-api" / "target" / "xiaoyi-rag-server-0.1.0-SNAPSHOT.jar"
AI_DIR = REPO_ROOT / "services" / "ai-api"
ARTIFACTS = REPO_ROOT / "test-artifacts"
PIDS = ARTIFACTS / "p7-pids.json"
BASE_JAVA = "http://127.0.0.1:8080"
BASE_AI = "http://127.0.0.1:8000"


def _detached_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return 0


def _wait(url: str, timeout: float, headers: dict[str, str] | None = None) -> bool:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = repr(exc)
        time.sleep(0.3)
    print(f"[p7_up] 健康检查超时 {url}: {last}", file=sys.stderr)
    return False


def _read_pids() -> dict[str, int]:
    if not PIDS.exists():
        return {}
    try:
        return json.loads(PIDS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_pids(data: dict[str, int]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    PIDS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill(pid: int | None) -> None:
    if not pid or not _alive(pid):
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"] if sys.platform == "win32" else ["kill", "-9", str(pid)],
        capture_output=True,
        check=False,
    )
    time.sleep(1.0)


def start_python(env: dict[str, str]) -> int:
    log = open(ARTIFACTS / "p7-python.log", "ab")  # noqa: SIM115 - 交给子进程持有
    # Python 侧状态目录与 Java 落盘目录必须分开：J2 的 clean_storage 会清空
    # STORAGE_ROOT，若 ai-state.sqlite3 落在里面会被正在运行的 uvicorn 占住（WinError 32）。
    ai_env = dict(env)
    ai_env["STORAGE_ROOT"] = env.get("AI_STORAGE_ROOT") or env["STORAGE_ROOT"]
    proc = subprocess.Popen(
        # --timeout-keep-alive 75：uvicorn 默认 5 秒就回收空闲连接，而 JDK HttpClient
        # 的连接池会继续复用它们，下一次写请求体直接拿到 Connection reset，
        # Java 侧翻成 50301「AI 服务不可用」。把服务端 keep-alive 抬到高于
        # JDK 默认 1200s 之外的常见空闲窗口，让对端回收不再是常态。
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--timeout-keep-alive",
            "75",
        ],
        cwd=str(AI_DIR),
        env=ai_env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=_detached_flags(),
        close_fds=True,
    )
    return proc.pid


def start_java(env: dict[str, str]) -> int:
    log = open(ARTIFACTS / "p7-java.log", "ab")  # noqa: SIM115
    # gate-probe profile 才注册 /__gate/throw（GateProbeController），J1 的
    # 「错误码 → HTTP 状态码」黑盒用例靠它真的走一遍 GlobalExceptionHandler。
    profiles = os.getenv("P7_SPRING_PROFILES", "gate-probe")
    cmd = [os.getenv("JAVA_EXE", "java"), "-jar", str(JAVA_JAR)]
    if profiles:
        cmd.append(f"--spring.profiles.active={profiles}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT / "services" / "java-api"),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=_detached_flags(),
        close_fds=True,
    )
    return proc.pid


def env_or_user_registry(name: str, default: str = "") -> str:
    """与 test/conftest.py 同一套回落：本机口令在 HKCU\\Environment，进程环境里通常没有。"""
    value = os.getenv(name)
    if value:
        return value
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            return default
    return default


def build_env(cfg: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MYSQL_HOST": env_or_user_registry("MYSQL_HOST", "127.0.0.1"),
            "MYSQL_PORT": env_or_user_registry("MYSQL_PORT", "3306"),
            "MYSQL_USER": env_or_user_registry("MYSQL_USER", "root"),
            "MYSQL_PASSWORD": env_or_user_registry("MYSQL_PASSWORD"),
            "INTERNAL_TOKEN": cfg["INTERNAL_TOKEN"],
            "STORAGE_ROOT": cfg["STORAGE_ROOT"],
            "AI_STORAGE_ROOT": cfg.get("AI_STORAGE_ROOT", ""),
            "AUTH_JWT_SECRET": cfg["AUTH_JWT_SECRET"],
            "AUTH_JWT_ISSUER": cfg["AUTH_JWT_ISSUER"],
            "AUTH_BOOTSTRAP_USERNAME": cfg["AUTH_BOOTSTRAP_USERNAME"],
            "AUTH_BOOTSTRAP_PASSWORD": cfg["AUTH_BOOTSTRAP_PASSWORD"],
            "AUTH_SECONDARY_BOOTSTRAP_USERNAME": cfg["AUTH_SECONDARY_BOOTSTRAP_USERNAME"],
            "AUTH_SECONDARY_BOOTSTRAP_PASSWORD": cfg["AUTH_SECONDARY_BOOTSTRAP_PASSWORD"],
            "MYSQL_DATABASE": cfg["MYSQL_DATABASE"],
            # 默认走真实 Python provider。J3/J5 里有一批用例依赖 MockAiClient 的
            # [fail] 降级标记与关键词命中打分，那些门禁要用 P7_AI_MOCK=true 起服务再跑。
            "AI_MOCK": os.getenv("P7_AI_MOCK", "false"),
            "AI_SERVICE_URL": BASE_AI,
            # 入库阶段节拍：0 = 全速。P7 设成大于 Java 轮询间隔（1000ms），
            # 否则 parsing→splitting→embedding→summarizing→done 在毫秒内跑完，轮询只抓得到首尾。
            "INGEST_STAGE_DELAY_MS": cfg.get("INGEST_STAGE_DELAY_MS", "0"),
        }
    )
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart-python", action="store_true")
    parser.add_argument("--restart-java", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    cfg = load()
    env = build_env(cfg)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    pids = _read_pids()

    if not JAVA_JAR.exists():
        print(f"[p7_up] 缺 jar：{JAVA_JAR}，先跑 mvn -q -DskipTests package", file=sys.stderr)
        return 2

    ai_health = f"{BASE_AI}/internal/v1/health"
    ai_headers = {"X-Internal-Token": cfg["INTERNAL_TOKEN"]}

    if args.restart_python or not _wait(ai_health, 1.0, ai_headers):
        _kill(pids.get("python"))
        pids["python"] = start_python(env)
        _write_pids(pids)
        if not _wait(ai_health, args.timeout, ai_headers):
            return 1
        print(f"[p7_up] python ready pid={pids['python']}")

    if args.restart_java or not _wait(f"{BASE_JAVA}/api/v1/health", 1.0):
        _kill(pids.get("java"))
        pids["java"] = start_java(env)
        _write_pids(pids)
        if not _wait(f"{BASE_JAVA}/api/v1/health", args.timeout):
            return 1
        print(f"[p7_up] java ready pid={pids['java']}")

    print(json.dumps(pids, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
