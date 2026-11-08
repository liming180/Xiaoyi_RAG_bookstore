"""生成 A3 报告 `test-artifacts/backend-gate-A3.json`。

数字全部来自实际跑过的命令，不接受手填：
* `a3-compare-real.json` / `a3-compare-rerank.json` 由 `tools/a3_compare.py` 产出；
* 套件与 Java 的数字在这里跑一遍取 exit code 与最后一行统计；
* 架构快照行数读文件本身。

用法（仓库根）：
    python tools/write_a3_report.py
    python tools/write_a3_report.py --skip-suites   # 只汇总已有产物
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "test-artifacts"
REPORT = ARTIFACTS / "backend-gate-A3.json"
SNAPSHOT = ROOT / "docs" / "03-架构评审" / "snapshot" / "架构快照.md"

PYTEST_SUMMARY = re.compile(r"(\d+) passed(?:, (\d+) skipped)?(?:, \d+ warning)?")
MVN_SUMMARY = re.compile(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)")


SUREFIRE_LINE = re.compile(
    r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)"
)


def surefire_totals(reports: Path) -> dict[str, int] | None:
    """汇总 `target/surefire-reports/*.txt` 的 Tests run 行。

    为什么不解析 mvn 的 stdout：`mvn -q verify` 只输出失败栈，成功时不打印
    `Tests run:` 汇总行（实测 tail 200 行里一条都没有）。报告文件才是权威来源。
    """
    if not reports.is_dir():
        return None
    totals = {"run": 0, "failures": 0, "errors": 0, "skipped": 0}
    found = False
    for path in sorted(reports.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = SUREFIRE_LINE.search(text)
        if not match:
            continue
        found = True
        for index, key in enumerate(("run", "failures", "errors", "skipped"), start=1):
            totals[key] += int(match.group(index))
    return totals if found else None


def run(cmd: list[str], cwd: Path, timeout: int = 1800) -> dict[str, Any]:
    """跑一条命令并取 exit/耗时/末行。

    Windows 上 `mvn` 是 `mvn.cmd`，`subprocess.run(["mvn", ...])` 会直接
    `FileNotFoundError: [WinError 2]`（CreateProcess 只认 exe）。所以先 `shutil.which`
    解析成绝对路径，再经 `cmd /c` 调一次。
    """
    resolved = list(cmd)
    if os.name == "nt":
        found = shutil.which(cmd[0])
        if found:
            resolved = ["cmd", "/c", found, *cmd[1:]]
    started = time.perf_counter()
    proc = subprocess.run(
        resolved, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    elapsed = round((time.perf_counter() - started) * 1000)
    tail = (proc.stdout or "").strip().splitlines()
    return {
        "cmd": " ".join(cmd),
        "cwd": str(cwd.relative_to(ROOT)) or ".",
        "exit": proc.returncode,
        "elapsedMs": elapsed,
        "summary": tail[-1] if tail else "",
        # mvn -q 下「Tests run:」汇总行不在末行（测试里故意打的异常栈会跟在后面），
        # 所以留一段尾部全文供正则搜索；只留 200 行避免报告膨胀。
        "stdoutTail": tail[-200:],
        "stderrTail": (proc.stderr or "").strip().splitlines()[-3:],
    }


def load_compare(name: str) -> dict[str, Any] | None:
    path = ARTIFACTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compare_gate(compare: dict[str, Any] | None, *, expect_rerank: bool) -> dict[str, Any]:
    if compare is None:
        return {"ok": False, "status": "missing", "note": "对照数据未生成"}
    summary = compare["summary"]
    hybrid = summary["hybrid"]
    rrf = summary["rrf"]
    # 判据：降级路径不得比 rrf 更差；接了 rerank 时同样不得更差（否则说明顺序被覆盖）。
    ok = hybrid["mrr"] >= rrf["mrr"] - 1e-9 and hybrid["hitRate"] >= rrf["hitRate"]
    return {
        "ok": ok,
        "status": "verified",
        "embeddingProvider": compare.get("embeddingProvider"),
        "k": compare.get("k"),
        "cases": len(compare["cases"]),
        "modes": {name: summary[name] for name in summary},
        "judgement": "hybrid 的 MRR/hit@k 不低于 rrf",
        "rerankConfigured": expect_rerank,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-suites", action="store_true", help="不重跑 pytest / mvn，只汇总已有数据")
    args = parser.parse_args()

    gates: dict[str, Any] = {}

    if args.skip_suites:
        # 复用上一次已跑出的门禁结果（连 exit/耗时/测试数一起），
        # 否则 --skip-suites 会把 gates 清空、报告里只剩对照数据。
        if REPORT.exists():
            previous = json.loads(REPORT.read_text(encoding="utf-8"))
            gates = previous.get("gates") or {}
    else:
        gates["a3-suite"] = run(
            [sys.executable, "-X", "utf8", "-m", "pytest", "A3-hybrid", "-q", "--no-header"],
            cwd=ROOT / "test",
        )
        gates["regression-a1-a2-a3-j6"] = run(
            [
                sys.executable, "-X", "utf8", "-m", "pytest",
                "A3-hybrid", "A2-rag", "A1-ai-skeleton", "J6-integration", "-q", "--no-header",
            ],
            cwd=ROOT / "test",
        )
        gates["java-verify"] = run(["mvn", "-q", "verify"], cwd=ROOT / "server-java", timeout=2400)

    for key, gate in gates.items():
        gate["ok"] = gate["exit"] == 0
        # java-verify 的统计行不在 mvn stdout 里（-q 成功时一条都不打），只能读 surefire 报告；
        # 但 --skip-suites 复用上一轮 gates 时 tests 已经填好了，不能被 PYTEST_SUMMARY 覆盖成 None。
        if key == "java-verify":
            if gate.get("tests") is None:
                gate["tests"] = surefire_totals(ROOT / "server-java" / "target" / "surefire-reports")
        else:
            match = PYTEST_SUMMARY.search(gate["summary"])
            gate["tests"] = (
                {"passed": int(match.group(1)), "skipped": int(match.group(2) or 0)}
                if match else None
            )
        # stdoutTail 只用来解析，不进报告正文。
        gate.pop("stdoutTail", None)

    real = compare_gate(load_compare("a3-compare-real.json"), expect_rerank=False)
    rerank = compare_gate(load_compare("a3-compare-rerank.json"), expect_rerank=True)

    snapshot_lines = (
        len(SNAPSHOT.read_text(encoding="utf-8").splitlines()) if SNAPSHOT.exists() else 0
    )

    report: dict[str, Any] = {
        "stage": "A3",
        "title": "混合检索：中文 BM25 + 自实现 RRF + 可降级重排 + 查询改写",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pass": all(g.get("ok") for g in gates.values()) and real["ok"] and rerank["ok"] if gates else real["ok"],
        "gates": gates,
        "compare": {"localFallback": real, "withRerank": rerank},
        "newModules": [
            "server-ai/app/core/rag/retriever.py",
            "server-ai/app/core/rag/fusion.py",
            "server-ai/app/core/rag/reranker.py",
            "test/A3-hybrid/test_rrf.py",
            "test/A3-hybrid/test_rerank.py",
            "test/A3-hybrid/test_modes.py",
            "tools/a3_compare.py",
            "tools/write_a3_report.py",
        ],
        "changedModules": [
            "server-ai/app/config.py（RETRIEVAL_* / RERANK_* 九项）",
            "server-ai/app/core/rag/pipeline.py（candidates 入参 + diagnostics）",
            "server-ai/app/services/ingest.py（四档 retrieve + _scoped_rows）",
            "server-ai/app/services/chat.py（history 透传）",
            "server-ai/app/api/routes.py（retrieval_mode 查询参数）",
            "server-ai/requirements.txt（jieba / rank-bm25）",
            "deploy/docker-compose.yml、localdb.yml、localdb-prebuilt.yml（RETRIEVAL_*/RERANK_*）",
            "deploy/local-mysql.env.example（A3 配置段）",
        ],
        "fixedDuringAcceptance": [
            "LexicalReranker 丢掉 RRF 分只按词面覆盖率重排，top-1 从 5/6 掉到 3/6；改为保序降级，词项分只做并列消歧",
            "HttpReranker 按 (-score, chunk_id) 二次排序，覆盖服务返回顺序；改为以服务数组顺序为准",
            "智谱 rerank 分数饱和（20 候选极差 <1e-5），top-1 掉到 2/6；加极差 <0.01 的饱和检测并退回保序",
            "trace 行多塞 score_stage 违反 InternalTraceRow 的 additionalProperties:false；档位改由 citations 表达",
            "diagnostics 一度塞进 HTTP 响应，违反 InternalRetrieveResult 的 additionalProperties:false；改为只在进程内",
            "tools/a3_compare.py 沿用外部 STORAGE_ROOT 导致任务被去重跳过建库、四档分数全 0.5；改为强制干净目录",
            "资料编号容量缺陷：chunk_id 契约是 ^D\\d{2}-C\\d{3}$，旧实现把 >99 的编号 clamp 成 99，第 100 份起全部撞主键（Milvus code=1100），且 MAX(doc_no)+1 分配导致「累计上传过 99 份」永久报废；改为最小空闲号 + 建库前对账回收（只回收早于本次任务开始的行、不重排编号）",
            "对账第一版无条件按本次资料集删除，把并发任务刚登记的资料删掉，J4 出现 3 条「资料 495 尚未登记编号」；改为 before 时间界 + 编号查不到就地补登记",
        ],
        "knownLimitations": [
            "6 问 6 语料规模太小，hit@3 四档全 6/6 已饱和，区分度只在 top-1 与 MRR 上",
            "本批语料上 dense 的 top-1 是 6/6，rrf/hybrid 的 5/6 并未超过它；混合检索的价值是向量质量不稳时仍能到 5/6",
            "智谱 rerank 实测分数饱和，当前配置下 hybrid 实际退化为 rrf；要真正提升需换有区分度的 rerank 服务",
            "RETRIEVAL_REWRITE 只在 real provider + 有 history 时生效，多轮指代消解只有单测覆盖，无端到端实测",
            "BM25 索引按 (user_id, task_id) 全量内存构建，语料量级到十万片时需要换持久化倒排",
            "一个用户同时最多 99 份资料（chunk_id 的文档号只有两位）；Java 上传接口没有前置拦截，用户要等到某次建库才拿到「已达上限」",
        ],
        "architectureSnapshotLines": snapshot_lines,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pass={report['pass']}  ->  {REPORT.relative_to(ROOT)}")
    for name, gate in gates.items():
        print(f"  {name:<22} exit={gate['exit']}  {gate.get('tests')}  {gate['summary'][:60]}")
    for name, gate in (("localFallback", real), ("withRerank", rerank)):
        if gate.get("status") == "missing":
            print(f"  compare/{name:<15} MISSING")
        else:
            print(
                f"  compare/{name:<15} ok={gate['ok']}  "
                f"hybrid mrr={gate['modes']['hybrid']['mrr']} rrf mrr={gate['modes']['rrf']['mrr']}"
            )
    print(f"  架构快照 {snapshot_lines} 行")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
