"""用 P7 真实环境跑 pytest：把 test-artifacts/p7-env.json 的凭据注入环境变量后再调 pytest。

用法::

    python tools/p7_pytest.py test/J7-isolation -q
    python tools/p7_pytest.py test/J4-ingest -q

为什么需要它：`test/conftest.py` 从环境变量读 INTERNAL_TOKEN / AUTH_JWT_SECRET /
MYSQL_DATABASE / JAVA_USERNAME 等，而 P7 用的是 `tools/p7_env.py` 生成并落盘的固定凭据。
手工在 PowerShell 里逐条 export 容易漏项（漏 INTERNAL_TOKEN 会让所有 internal 调用 401），
所以集中在这里注入一次。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p7_env import OUT, REPO_ROOT, load  # noqa: E402

# p7-env.json 的键与 conftest 读取的键基本同名，这几个需要额外映射。
EXTRA = {
    "JAVA_USERNAME": "AUTH_BOOTSTRAP_USERNAME",
    "JAVA_PASSWORD": "AUTH_BOOTSTRAP_PASSWORD",
    "JAVA_USERNAME_B": "AUTH_SECONDARY_BOOTSTRAP_USERNAME",
    "JAVA_PASSWORD_B": "AUTH_SECONDARY_BOOTSTRAP_PASSWORD",
    "BASE_JAVA": None,
    "BASE_AI": None,
}


def build_env() -> dict[str, str]:
    """返回注入了 P7 凭据的环境变量副本。"""
    cfg = load()
    env = dict(os.environ)
    for key, value in cfg.items():
        env[key] = str(value)
    for target, source in EXTRA.items():
        if source is None:
            continue
        if cfg.get(source):
            env[target] = str(cfg[source])
    env.setdefault("BASE_JAVA", "http://127.0.0.1:8080")
    env.setdefault("BASE_AI", "http://127.0.0.1:8000")
    # conftest 的破坏性 fixture 要求库名以 _gate 结尾，这里保证不会被误指到生产库。
    if not env.get("MYSQL_DATABASE", "").endswith("_gate"):
        raise SystemExit(f"MYSQL_DATABASE={env.get('MYSQL_DATABASE')!r} 不是门禁库，拒绝执行")
    return env


def main(argv: list[str]) -> int:
    if not OUT.exists():
        raise SystemExit(f"缺少 {OUT}，先跑 python tools/p7_env.py")
    args = argv or ["-q"]
    print(f"[p7_pytest] env={OUT.name} db={json.loads(OUT.read_text(encoding='utf-8'))['MYSQL_DATABASE']}")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=str(REPO_ROOT / "test"),
        env=build_env(),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
