"""前台跑 java（不脱离父进程），供 harness 后台作业托管。

用法（由 pwsh 的 run_in_background 启动）::

    python tools/p7_java_fg.py                 # 用 test-artifacts/p7-env.json
    python tools/local_mysql.py up             # 用 deploy/local-mysql.env（传 env 进来）

为什么不用 p7_up.start_java：本机沙箱在命令结束时回收进程树，
`DETACHED_PROCESS` 起的 java 会随 pwsh 调用结束被杀，日志也写不进文件。
把 java 挂在一个长期存活的后台作业里最稳。

`main(env=...)` 允许调用方直接把装配好的环境传进来；不传时才回落到
p7-env.json。早期版本无条件 `load()`，导致 local_mysql.up 传进来的
MYSQL_DATABASE / bootstrap 账号被 p7-env.json 覆盖。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p7_up  # noqa: E402
from p7_env import load  # noqa: E402


def main(env: dict[str, str] | None = None) -> int:
    if env is None:
        cfg = load()
        env = p7_up.build_env(cfg)
    profiles = os.getenv("P7_SPRING_PROFILES", "gate-probe")
    cmd = [os.getenv("JAVA_EXE", "java"), "-jar", str(p7_up.JAVA_JAR)]
    if profiles:
        cmd.append(f"--spring.profiles.active={profiles}")
    print("[p7_java_fg] " + " ".join(cmd), flush=True)
    print(f"[p7_java_fg] database={env.get('MYSQL_DATABASE')} bootstrap={env.get('AUTH_BOOTSTRAP_USERNAME')}", flush=True)
    log_path = p7_up.ARTIFACTS / "p7-java-fg.log"
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=str(p7_up.REPO_ROOT / "server-java"),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        print(f"[p7_java_fg] pid={proc.pid} log={log_path}", flush=True)
        return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
