"""本机 MySQL 模式：不依赖 Docker 镜像，空库由 Java/Flyway 自动迁移。

准备：复制 deploy/local-mysql.env.example 为 deploy/local-mysql.env，填入本机
MySQL 密码与随机密钥。也可以只用进程环境变量；未提供 MYSQL_PASSWORD 时，
Windows 会读取当前用户的 HKCU\\Environment（不会打印密码）。

    python scripts/local_mysql.py prepare --db-name xiaoyi_rag_local_gate
    python scripts/local_mysql.py up
    python scripts/local_mysql.py verify
    python scripts/local_mysql.py verify --browser   # 另需真实浏览器双账号验收
    python scripts/local_mysql.py status
    python scripts/local_mysql.py down
    python scripts/local_mysql.py drop-db --yes       # 只删本工具的独立验收库

up 启动 Python/前台托管 Java 与前端静态代理。由终端或 Harness 后台作业托管，
关闭该作业即停止这些进程；MySQL Windows 服务本身不被停止。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import p7_up

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "test-artifacts"
STATE_FILE = ARTIFACTS / "local-mysql-state.json"
DEFAULT_ENV_FILE = REPO_ROOT / "deploy" / "local-mysql.env"
DEFAULT_DB = "xiaoyi_rag_local_gate"
DEFAULT_WEB_PORT = 4173


def load_env_file(path: Path) -> dict[str, str]:
    """读简单 KEY=VALUE，不执行 shell，不在输出中泄露口令。"""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{number} 不是 KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in {'"', "'"} and value.endswith(value[:1]):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        result[key] = value
    return result


def config(env_file: Path | None = None, db_name: str | None = None) -> dict[str, str]:
    values = load_env_file(env_file or DEFAULT_ENV_FILE)
    for key in (
        "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE",
        "AUTH_JWT_SECRET", "AUTH_JWT_ISSUER", "INTERNAL_TOKEN",
        "AUTH_BOOTSTRAP_USERNAME", "AUTH_BOOTSTRAP_PASSWORD",
        "AUTH_SECONDARY_BOOTSTRAP_USERNAME", "AUTH_SECONDARY_BOOTSTRAP_PASSWORD",
        "STORAGE_ROOT", "AI_STORAGE_ROOT", "AI_MOCK", "INGEST_STAGE_DELAY_MS",
    ):
        if os.getenv(key):
            values[key] = os.environ[key]
    values["MYSQL_HOST"] = values.get("MYSQL_HOST") or "127.0.0.1"
    values["MYSQL_PORT"] = values.get("MYSQL_PORT") or "3306"
    values["MYSQL_USER"] = values.get("MYSQL_USER") or "root"
    values["MYSQL_PASSWORD"] = p7_up.env_or_user_registry("MYSQL_PASSWORD", values.get("MYSQL_PASSWORD", ""))
    values["MYSQL_DATABASE"] = db_name or values.get("MYSQL_DATABASE") or DEFAULT_DB
    values["AUTH_JWT_ISSUER"] = values.get("AUTH_JWT_ISSUER", "xiaoyi-rag")
    values["STORAGE_ROOT"] = values.get("STORAGE_ROOT") or str(ARTIFACTS / "local-mysql" / "java")
    values["AI_STORAGE_ROOT"] = values.get("AI_STORAGE_ROOT") or str(ARTIFACTS / "local-mysql" / "ai")
    values["AI_MOCK"] = values.get("AI_MOCK", "false")
    values["INGEST_STAGE_DELAY_MS"] = values.get("INGEST_STAGE_DELAY_MS", "0")
    return values


def validate(cfg: dict[str, str], require_accounts: bool = False) -> None:
    name = cfg["MYSQL_DATABASE"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("MYSQL_DATABASE 只能含字母、数字、下划线")
    if not (name.endswith("_gate") or name.endswith("_test")):
        raise ValueError("独立库名必须以 _gate 或 _test 结尾，避免误动开发库")
    if not cfg["MYSQL_PASSWORD"]:
        raise ValueError("缺 MYSQL_PASSWORD：写入 deploy/local-mysql.env 或当前用户环境变量")
    if len(cfg.get("AUTH_JWT_SECRET", "").encode("utf-8")) < 32:
        raise ValueError("AUTH_JWT_SECRET 至少 32 UTF-8 字节")
    if not cfg.get("INTERNAL_TOKEN", "").strip():
        raise ValueError("INTERNAL_TOKEN 必须显式设置")
    if require_accounts:
        for prefix in ("AUTH_BOOTSTRAP", "AUTH_SECONDARY_BOOTSTRAP"):
            username, password = cfg.get(prefix + "_USERNAME", ""), cfg.get(prefix + "_PASSWORD", "")
            if not username.strip() or not 12 <= len(password.encode("utf-8")) <= 72:
                raise ValueError(f"{prefix}_USERNAME 必填，{prefix}_PASSWORD 必须 12–72 UTF-8 字节")


def connect(cfg: dict[str, str], database: str | None = None):
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("缺 PyMySQL：python -m pip install PyMySQL") from exc
    return pymysql.connect(
        host=cfg["MYSQL_HOST"], port=int(cfg["MYSQL_PORT"]), user=cfg["MYSQL_USER"],
        password=cfg["MYSQL_PASSWORD"], database=database, charset="utf8mb4",
        connect_timeout=5, read_timeout=10, write_timeout=10,
    )


def prepare(cfg: dict[str, str]) -> dict[str, object]:
    validate(cfg)
    db = cfg["MYSQL_DATABASE"]
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), @@version_comment")
            version, edition = cur.fetchone()
            cur.execute("SHOW DATABASES")
            before = {row[0] for row in cur.fetchall()}
            existed = db in before
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
            cur.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (db,))
            if cur.fetchone() is None:
                raise RuntimeError("CREATE DATABASE 返回成功但数据库仍不存在")
    print(f"[local-mysql] 已连接 MySQL {version} ({edition})")
    print(f"[local-mysql] 独立库 {db} 已就绪；此前{'已存在' if existed else '不存在，本次创建'}")
    print("[local-mysql] 表结构不由脚本手写：up 启动 Java 时由 Flyway V1–V7 迁移")
    return {"database": db, "createdNow": not existed, "mysqlVersion": version, "mysqlEdition": edition}


def wait(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
    quiet: bool = False,
) -> bool:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = repr(exc)
        time.sleep(0.5)
    # quiet=True 用于可选探针（例如 status 里的 web）：探测失败是正常状态，
    # 不该往 stderr 写一行「等待失败」，否则 PowerShell 会把它包成
    # NativeCommandError，把一次正常的状态查询变成红色的报错输出。
    if not quiet:
        print(f"[local-mysql] 等待失败：{url}；{last}", file=sys.stderr)
    return False


def read_state() -> dict[str, object]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(value: dict[str, object]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"http://127.0.0.1:8080{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def database_state(cfg: dict[str, str]) -> dict[str, object]:
    with connect(cfg, cfg["MYSQL_DATABASE"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", (cfg["MYSQL_DATABASE"],))
            tables = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT VERSION, DESCRIPTION, SUCCESS FROM flyway_schema_history ORDER BY INSTALLED_RANK")
            migrations = [{"version": row[0], "description": row[1], "success": bool(row[2])} for row in cur.fetchall()]
            cur.execute("SELECT id, username, LEFT(password_hash, 7) FROM user ORDER BY id")
            users = [{"id": row[0], "username": row[1], "passwordHashPrefix": row[2]} for row in cur.fetchall()]
    return {"tables": tables, "tableCount": len(tables), "migrations": migrations, "users": users}


def verify(cfg: dict[str, str]) -> dict[str, object]:
    validate(cfg, require_accounts=True)
    if not wait("http://127.0.0.1:8080/api/v1/health", timeout=3):
        raise RuntimeError("Java 未就绪，先运行 python scripts/local_mysql.py up")
    if not wait("http://127.0.0.1:8000/internal/v1/health", {"X-Internal-Token": cfg["INTERNAL_TOKEN"]}, timeout=3):
        raise RuntimeError("Python 未就绪，先运行 python scripts/local_mysql.py up")
    logins = []
    for prefix in ("AUTH_BOOTSTRAP", "AUTH_SECONDARY_BOOTSTRAP"):
        username, password = cfg[prefix + "_USERNAME"], cfg[prefix + "_PASSWORD"]
        status, body = api("POST", "/api/v1/auth/login", body={"username": username, "password": password})
        data = body.get("data") or {}
        if status != 200 or body.get("code") != 0 or not data.get("token"):
            raise AssertionError(f"{username} 登录失败：HTTP {status} {body}")
        user = data.get("user") or {}
        if user.get("username") != username or not data.get("expiresIn"):
            raise AssertionError(f"{username} 登录响应身份/有效期不对：{data}")
        logins.append({"username": username, "userId": user.get("id"), "expiresIn": data.get("expiresIn"), "jwtSubjectPresent": True})
    if logins[0]["userId"] == logins[1]["userId"]:
        raise AssertionError("双账号登录得到同一个 user.id")
    db = database_state(cfg)
    required = {"user", "document", "index_task", "chunk", "conversation", "message", "eval_run", "experiment", "flyway_schema_history"}
    if not required.issubset(db["tables"]):
        raise AssertionError(f"迁移后缺表：{sorted(required - set(db['tables']))}")
    if not db["migrations"] or not all(row["success"] for row in db["migrations"]):
        raise AssertionError(f"Flyway 有失败记录：{db['migrations']}")
    report = {
        "phase": "local-mysql", "pass": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dockerRequired": False, "database": cfg["MYSQL_DATABASE"], **db, "logins": logins,
        "health": {"java": 200, "python": 200},
        "note": "空库由 Java/Flyway 自动建表，不手工重复导入迁移 SQL。",
    }
    path = ARTIFACTS / "local-mysql-verify.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[local-mysql] 验证报告：{path}")
    return report


def up(cfg: dict[str, str], timeout: float) -> int:
    validate(cfg, require_accounts=True)
    if not (p7_up.JAVA_JAR).exists():
        raise RuntimeError("缺 Java jar：先 cd services/java-api && mvn -q -DskipTests package")
    # 上一次 up 留下的进程先收掉，否则 8000/8080 会端口冲突，
    # 且新起的 Java 会连到旧库/旧账号上，verify 时表现为登录 401。
    stale = read_state()
    for key in ("python", "java", "web"):
        pid = stale.get(key)
        if isinstance(pid, int):
            p7_up._kill(pid)
    prepare(cfg)
    env = p7_up.build_env(cfg)
    (ARTIFACTS / "local-mysql" / "java").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "local-mysql" / "ai").mkdir(parents=True, exist_ok=True)
    env["STORAGE_ROOT"] = cfg["STORAGE_ROOT"]
    env["AI_STORAGE_ROOT"] = cfg["AI_STORAGE_ROOT"]
    env["AI_MOCK"] = cfg["AI_MOCK"]
    env["INGEST_STAGE_DELAY_MS"] = cfg["INGEST_STAGE_DELAY_MS"]
    env["P7_WEB_DIST"] = str(REPO_ROOT / "frontend" / "dist")
    env["P7_ENV_FILE"] = str(ARTIFACTS / "local-mysql-public.json")
    public = {k: cfg[k] for k in (
        "AUTH_BOOTSTRAP_USERNAME", "AUTH_BOOTSTRAP_PASSWORD",
        "AUTH_SECONDARY_BOOTSTRAP_USERNAME", "AUTH_SECONDARY_BOOTSTRAP_PASSWORD",
    )}
    (ARTIFACTS / "local-mysql-public.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[local-mysql] 启动 Python（8000）…", flush=True)
    python_pid = p7_up.start_python(env)
    write_state({"database": cfg["MYSQL_DATABASE"], "python": python_pid, "java": None, "web": None})
    if not wait("http://127.0.0.1:8000/internal/v1/health", {"X-Internal-Token": cfg["INTERNAL_TOKEN"]}, timeout):
        return 1
    print(f"[local-mysql] Python ready pid={python_pid}", flush=True)
    print("[local-mysql] 前台托管 Java（8080），Flyway 正在执行空库迁移…", flush=True)
    # 默认 gate-probe：J1「错误码 → HTTP 状态码」黑盒用例依赖它注册的 /__gate/throw，
    # 与 scripts/p7_up.py 的默认值保持一致。要跑纯业务实例（不含测试端点）时显式设
    # P7_SPRING_PROFILES= 覆盖成空值。
    os.environ.setdefault("P7_SPRING_PROFILES", "gate-probe")
    import p7_java_fg

    # 把装配好的 env 直接交给 p7_java_fg：它内部的 load() 会读
    # test-artifacts/p7-env.json，用那里的 MYSQL_DATABASE / 账号覆盖本文件的配置。
    return p7_java_fg.main(env)


def status(cfg: dict[str, str]) -> int:
    db = {"database": cfg["MYSQL_DATABASE"]}
    try:
        db.update(database_state(cfg))
    except Exception as exc:
        db["error"] = str(exc)
    java = wait("http://127.0.0.1:8080/api/v1/health", timeout=1, quiet=True)
    python = wait(
        "http://127.0.0.1:8000/internal/v1/health",
        {"X-Internal-Token": cfg.get("INTERNAL_TOKEN", "")},
        timeout=1,
        quiet=True,
    )
    # web 是可选件：浏览器验收（apps/web/scripts/p7-browser.mjs）会自己起 4173 的静态服务器，
    # 本工具不托管前端。所以 web=false 只作为信息输出，不参与退出码。
    web = wait(f"http://127.0.0.1:{DEFAULT_WEB_PORT}/", timeout=1, quiet=True)
    print(
        json.dumps(
            {
                "mysql": db,
                "java": java,
                "python": python,
                "web": web,
                "webNote": "可选：浏览器验收脚本自起 4173，不托管时恒为 false",
                "state": read_state(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if (java and python) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "up", "verify", "status", "down", "drop-db"])
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--db-name")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    cfg = config(args.env_file, args.db_name)
    if args.command == "prepare":
        prepare(cfg)
        return 0
    if args.command == "up":
        return up(cfg, args.timeout)
    if args.command == "verify":
        verify(cfg)
        if args.browser:
            public = ARTIFACTS / "local-mysql-public.json"
            env = dict(os.environ, P7_ENV_FILE=str(public))
            return subprocess.run(["node", "scripts/p7-browser.mjs"], cwd=REPO_ROOT / "frontend", env=env).returncode
        return 0
    if args.command == "status":
        return status(cfg)
    if args.command == "down":
        state = read_state()
        for key in ("python", "java", "web"):
            p7_up._kill(state.get(key) if isinstance(state.get(key), int) else None)
        STATE_FILE.unlink(missing_ok=True)
        print("[local-mysql] 已停止本工具启动的 Python/Java/前端；未停止 MySQL 服务，未删库。")
        return 0
    validate(cfg)
    if not args.yes:
        print("drop-db 需要 --yes；这是独立验收库的不可恢复删除。", file=sys.stderr)
        return 2
    with connect(cfg) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE `{cfg['MYSQL_DATABASE']}`")
            conn.commit()
    print(f"[local-mysql] 已删除独立库 {cfg['MYSQL_DATABASE']}，未触碰 xiaoyi_rag 开发库。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, AssertionError) as exc:
        print(f"[local-mysql] {exc}", file=sys.stderr)
        raise SystemExit(2)
