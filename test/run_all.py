"""按 J0 → J1 → J2 → J3 → J4 → J5 → J6 → A1 → A2 → A3 顺序跑全量黑盒验收。

用法::

    py -3.12 -X utf8 test/run_all.py            # 全量
    py -3.12 -X utf8 test/run_all.py J0 A1      # 只跑指定阶段
    py -3.12 -X utf8 test/run_all.py --list     # 只列阶段

产物：``test-artifacts/backend-gate-all.json``，格式与
`04_后端开发提示词.md` §14 的门禁报告一致：

    {"phase": "all", "pass": true, "timestamp": 1730000000,
     "gates": [{"key": "J0", "ok": true, "exitCode": 0, "elapsedMs": 123, "counts": {...}}]}

任一阶段有失败即 ``exit 1``，并打印失败用例的完整 assert 消息。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
ARTIFACTS = REPO_ROOT / "test-artifacts"
REPORT = ARTIFACTS / "backend-gate-all.json"

#: 阶段顺序即执行顺序（手册 §3.1）。
STAGES: list[tuple[str, str]] = [
    ("J0", "J0-contract"),
    ("J1", "J1-skeleton"),
    ("J2", "J2-crud"),
    ("J3", "J3-sse"),
    ("J4", "J4-ingest"),
    ("J5", "J5-eval"),
    ("J6", "J6-integration"),
    ("A1", "A1-ai-skeleton"),
    ("A2", "A2-rag"),
    ("A3", "A3-hybrid"),
]


def _has_tests(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("test_*.py"))


def run_stage(key: str, folder_name: str) -> dict:
    folder = TEST_DIR / folder_name
    if not _has_tests(folder):
        print(f"[{key}] 跳过：{folder_name}/ 下没有 test_*.py")
        return {
            "key": key,
            "ok": True,
            "skipped": True,
            "exitCode": 0,
            "elapsedMs": 0,
        }

    cmd = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        str(folder),
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    print(f"[{key}] {' '.join(cmd)}")
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    elapsed_ms = int((time.monotonic() - started) * 1000)

    ok = proc.returncode == 0
    if not ok:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    tail = (proc.stdout or "").strip().splitlines()
    print(f"[{key}] {'PASS' if ok else 'FAIL'} ({elapsed_ms}ms) {tail[-1] if tail else ''}")

    return {
        "key": key,
        "ok": ok,
        "exitCode": proc.returncode,
        "elapsedMs": elapsed_ms,
        "summary": tail[-1] if tail else "",
    }


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for key, folder in STAGES:
            print(f"{key:3} {folder}")
        return 0

    wanted = [a.upper() for a in argv if not a.startswith("-")]
    stages = [s for s in STAGES if not wanted or s[0] in wanted]

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    gates = [run_stage(key, folder) for key, folder in stages]

    passed = all(g["ok"] for g in gates)
    report = {
        "phase": "all",
        "pass": passed,
        "timestamp": int(time.time()),
        "gates": gates,
    }
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = sum(1 for g in gates if not g.get("skipped"))
    failed = [g["key"] for g in gates if not g["ok"]]
    print()
    print(f"阶段 {len(gates)} 个（实跑 {total} 个），失败 {len(failed)} 个")
    print(f"报告：{REPORT}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
