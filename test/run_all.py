"""按 J0 → J1 → J2 → J3 → J4 → J5 → J6 → J7 → A1 → A2 → A3 顺序跑黑盒验收。

用法::

    py -3.12 -X utf8 test/run_all.py            # 按顺序跑全部阶段
    py -3.12 -X utf8 test/run_all.py J0 A1      # 只跑指定阶段
    py -3.12 -X utf8 test/run_all.py --list     # 只列阶段与各自要求的 provider 档位
    py -3.12 -X utf8 test/run_all.py J3 --fresh # 丢弃历史，只留本轮

产物：``test-artifacts/backend-gate-all.json``，格式与
`04_后端开发提示词.md` §14 的门禁报告一致：

    {"phase": "all", "pass": true, "partial": false,
     "coveredStages": ["J0", "J1", ...], "missingStages": [],
     "providerProfiles": ["mock", "real"], "timestamp": 1730000000,
     "runs": [{"timestamp": 1730000000, "stages": ["J0"], "providers": ["real"]}],
     "gates": [{"key": "J0", "ok": true, "provider": "real", "ranAt": 1730000000,
                "exitCode": 0, "elapsedMs": 123, "summary": "79 passed in 4.2s"}]}

**关于 ``partial`` 与多轮合并**：J3/J5 断言的是 mock provider 的确定性输出，必须
``AI_MOCK=true``；其余阶段要真实 embedding/检索链路，必须 ``AI_MOCK=false``。两档互斥，
单次调用跑不出全量。所以默认沿用上一次报告里本轮没跑的阶段，把两轮拼成一份完整报告
（每条 gate 的 ``ranAt`` 标明属于哪一轮，``runs`` 记录每轮的覆盖范围）。
``partial: true`` 表示仍有阶段没被任何一轮覆盖；加 ``--fresh`` 丢弃历史只留本轮。

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

#: 阶段顺序即执行顺序（手册 §3.1）。第三项是该阶段要求的 Java provider 档位：
#:
#: * ``mock`` —— 断言的是 mock provider 的确定性输出（固定的阶段节拍、固定的评测分），
#:   必须 ``AI_MOCK=true``，否则数字对不上；
#: * ``real`` —— 要真实 embedding / 检索链路，必须 ``AI_MOCK=false``。
#:
#: 两个档位互斥，所以**一次 run_all 调用不可能覆盖全部阶段**，报告里用 ``partial``
#: 如实标注这次到底跑了哪几个（见 ``main`` 里的 ``report``）。
STAGES: list[tuple[str, str, str]] = [
    ("J0", "J0-contract", "real"),
    ("J1", "J1-skeleton", "real"),
    ("J2", "J2-crud", "real"),
    ("J3", "J3-sse", "mock"),
    ("J4", "J4-ingest", "real"),
    ("J5", "J5-eval", "mock"),
    ("J6", "J6-integration", "real"),
    ("J7", "J7-isolation", "real"),
    ("A1", "A1-ai-skeleton", "real"),
    ("A2", "A2-rag", "real"),
    ("A3", "A3-hybrid", "real"),
]


def _has_tests(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("test_*.py"))


def run_stage(key: str, folder_name: str, provider: str) -> dict:
    folder = TEST_DIR / folder_name
    if not _has_tests(folder):
        print(f"[{key}] 跳过：{folder_name}/ 下没有 test_*.py")
        return {
            "key": key,
            "ok": True,
            "skipped": True,
            "provider": provider,
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
        "provider": provider,
        "exitCode": proc.returncode,
        "elapsedMs": elapsed_ms,
        "summary": tail[-1] if tail else "",
    }


def _load_previous() -> dict:
    """读上一次的报告，用于把两档 provider 的结果拼成一份完整视图。

    没有历史就返回空 dict。历史文件坏了也不影响本次运行 —— 直接当没有。
    """
    if not REPORT.exists():
        return {}
    try:
        data = json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("gates"), list):
        return {}
    return data


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for key, folder, provider in STAGES:
            print(f"{key:3} {folder:16} provider={provider}")
        return 0

    wanted = [a.upper() for a in argv if not a.startswith("-")]
    unknown = [k for k in wanted if k not in {s[0] for s in STAGES}]
    if unknown:
        print(f"未知阶段：{', '.join(unknown)}；可用：{', '.join(s[0] for s in STAGES)}")
        return 2

    stages = [s for s in STAGES if not wanted or s[0] in wanted]
    providers = {s[2] for s in stages}
    ran_at = int(time.time())

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    gates = [run_stage(key, folder, provider) for key, folder, provider in stages]
    for gate in gates:
        gate["ranAt"] = ran_at

    # J3/J5 要 AI_MOCK=true，其余要 AI_MOCK=false，两档互斥 —— 单次调用必然只覆盖一部分。
    # 所以默认沿用上一次报告里本轮没跑的阶段（每条 gate 自带 ranAt，看得出是哪一轮的），
    # 这样跑完 real 档再跑 mock 档，就能拼出一份覆盖全部阶段的报告。
    # 想只要本轮结果就加 --fresh。
    previous = {} if "--fresh" in argv else _load_previous()
    fresh = {gate["key"]: gate for gate in gates}
    carried = {
        gate["key"]: gate
        for gate in previous.get("gates", [])
        if isinstance(gate, dict) and gate.get("key") in {s[0] for s in STAGES}
    }
    # 老版本写的报告没有 ranAt，用报告自身的 timestamp 兜底，免得合并后出现「不知道哪一轮」的条目。
    for gate in carried.values():
        if not gate.get("ranAt"):
            gate["ranAt"] = previous.get("timestamp")
    merged = [fresh.get(key) or carried.get(key) for key, _, _ in STAGES]
    merged = [gate for gate in merged if gate]

    covered = [gate["key"] for gate in merged]
    missing = [key for key, _, _ in STAGES if key not in covered]
    partial = bool(missing)
    passed = all(gate.get("ok") for gate in merged)

    runs = [r for r in previous.get("runs", []) if isinstance(r, dict)]
    runs.append(
        {
            "timestamp": ran_at,
            "stages": [s[0] for s in stages],
            "providers": sorted(providers),
        }
    )
    report = {
        "phase": "all",
        "pass": passed,
        "partial": partial,
        "coveredStages": covered,
        "missingStages": missing,
        "providerProfiles": sorted({gate.get("provider") for gate in merged if gate.get("provider")}),
        "timestamp": ran_at,
        "runs": runs[-10:],
        "gates": merged,
    }
    if partial:
        report["note"] = (
            "覆盖 "
            + ", ".join(covered)
            + "；未跑 "
            + ", ".join(missing)
            + "。J3/J5 需要 AI_MOCK=true，其余阶段需要 AI_MOCK=false，两档互斥，"
            "所以单次调用跑不全 —— 本文件是多次运行合并的结果，每条 gate 的 ranAt "
            "标明它属于哪一轮，runs 记录每轮覆盖了哪些阶段。"
        )
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    total = sum(1 for gate in gates if not gate.get("skipped"))
    failed = [gate["key"] for gate in gates if not gate["ok"]]
    print()
    print(f"本轮 {len(gates)} 个阶段（实跑 {total} 个），失败 {len(failed)} 个")
    print(f"合并后覆盖 {len(covered)}/{len(STAGES)} 个阶段：{', '.join(covered)}")
    if partial:
        # 缺的阶段里，有的只是「这次没点它」，有的是「必须换一档 provider 才跑得了」。
        # 分开说，免得看到「需要另一档 provider」就以为换个 flag 能一起跑。
        other = [key for key, _, prof in STAGES if key in missing and prof not in providers]
        same = [key for key, _, prof in STAGES if key in missing and prof in providers]
        if same:
            print(f"⚠ 未跑（同一档，可直接补跑）：{', '.join(same)}")
        if other:
            print(f"⚠ 未跑（需换 provider 档）：{', '.join(other)}")
    else:
        print("✓ 全部阶段已覆盖（两档 provider 各跑过一轮）")
    print(f"报告：{REPORT}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
