"""临时诊断：用 P7 环境前台起 java，捕获退出码与日志尾部。

用法：python tools/p7_java_probe.py [seconds]
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p7_up  # noqa: E402
from p7_env import load  # noqa: E402


def main() -> int:
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    cfg = load()
    env = p7_up.build_env(cfg)
    cmd = [os.getenv("JAVA_EXE", "java"), "-jar", str(p7_up.JAVA_JAR), "--spring.profiles.active=gate-probe"]
    print("[probe] cmd:", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(p7_up.REPO_ROOT / "server-java"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print("[probe] pid:", proc.pid)
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if p7_up._wait(f"{p7_up.BASE_JAVA}/api/v1/health", 1.0):
            print("[probe] health OK")
            break
        time.sleep(0.5)
    time.sleep(2.0)
    code = proc.poll()
    print("[probe] exited:", code)
    if code is None:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    print("[probe] output tail:")
    print("\n".join(out.splitlines()[-60:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
