"""A3 四档对照：dense / bm25 / rrf / hybrid 在同一批语料、同一批问题上的实测差异。

为什么要有这个工具：单测证明「每档形状正确」，但证明不了「混合检索确实更好」。
这里跑真实 app（进程内，mock provider + 内存向量库，无需 Milvus 与外网），
对每个问题记录四档的 top-k chunk_id、分数、档位与耗时，输出对照表与命中率。

用法（仓库根）：
    python tools/a3_compare.py
    python tools/a3_compare.py --json test-artifacts/a3-compare.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "data"
MODES = ("dense", "bm25", "rrf", "hybrid")

# 问题 → 期望命中的文档（用于算 hit@k）。都是语料里能查到的事实。
CASES: list[tuple[str, str, str]] = [
    ("普通图书最多借几本，借期多久？", "02_借阅规则.md", "borrow-limit"),
    ("续借能延长多少天？", "02_借阅规则.md", "renew-days"),
    ("自习区怎么预约，能坐多久？", "03_空间预约.md", "space-booking"),
    ("工具书可以外借吗？", "02_借阅规则.md", "reference-only"),
    ("读书会的活动时间改到什么时候？", "05_活动调整通知.md", "event-time"),
    ("期刊可以借回家看吗？", "04_期刊与工具书.md", "journal-loan"),
]


def _bootstrap() -> Any:
    """装配 app：默认 mock provider + 临时状态库 + 无 Milvus。

    已经设好的 `AI_PROVIDER` / `EMBEDDING_*` 一律尊重：要看真实 embedding 的效果，
    先在环境里填好 provider 再跑，不要在这里被默认值盖掉。
    """
    tmp = Path(tempfile.mkdtemp(prefix="a3-compare-"))
    os.environ.setdefault("AI_PROVIDER", "mock")
    os.environ.setdefault("MILVUS_URI", "")
    os.environ.setdefault("INGEST_STAGE_DELAY_MS", "0")
    os.environ.setdefault("INTERNAL_TOKEN", "a3-compare-token")
    # 强制用干净状态目录，绝不沿用外部 STORAGE_ROOT：
    # 沿用旧目录时 sqlite 里的任务会被 submission_key 去重命中而跳过建库，
    # 但新进程的内存向量库是空的，检索会落到 fallback 行上，
    # 表现为「四档分数全是 0.5、顺序退化成 chunk_id 升序」的假结果。
    os.environ["STORAGE_ROOT"] = str(tmp)
    sys.path.insert(0, str(ROOT / "server-ai"))
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        del sys.modules[name]
    import importlib

    return importlib.import_module("app.main")


def _ingest(client, module) -> str:
    """一次性提交全部语料，返回 task_id。"""
    documents = []
    for index, path in enumerate(sorted(DATA.glob("*.md")), start=1):
        documents.append({
            "doc_id": f"D{index:02d}",
            "name": path.name,
            "title": path.name,
            "text": path.read_text(encoding="utf-8"),
        })
    token = os.environ["INTERNAL_TOKEN"]
    resp = client.post(
        "/internal/v1/documents/parse",
        headers={"X-Internal-Token": token, "X-User-Id": "2"},
        json={
            "documents": documents,
            "chunk_size": 180,
            "overlap": 30,
            "submission_key": "sk-compare",
            "generation": "g-1",
        },
    )
    resp.raise_for_status()
    task_id = resp.json()["data"]["task_id"]
    task = client.get(
        f"/internal/v1/ingest/{task_id}",
        headers={"X-Internal-Token": token, "X-User-Id": "2"},
    ).json()["data"]
    assert task["status"] == "SUCCEEDED", task
    return task_id


def _retrieve(client, question: str, mode: str, k: int) -> dict[str, Any]:
    started = time.perf_counter()
    resp = client.post(
        "/internal/v1/retrieve",
        headers={"X-Internal-Token": os.environ["INTERNAL_TOKEN"], "X-User-Id": "2"},
        json={"question": question, "k": k, "mode": "rag", "history": []},
        params={"retrieval_mode": mode},
    )
    resp.raise_for_status()
    elapsed = (time.perf_counter() - started) * 1000
    data = resp.json()["data"]
    return {
        "elapsed_ms": round(elapsed, 2),
        "chunk_ids": [item["chunk_id"] for item in data["citations"]],
        "doc_titles": [item["doc_title"] for item in data["citations"]],
        "scores": [round(float(item["score"]), 6) for item in data["citations"]],
        "stages": [item["score_stage"] for item in data["citations"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A3 四档检索对照")
    parser.add_argument("--k", type=int, default=3, help="每档返回的引用条数，默认 3")
    parser.add_argument("--json", type=Path, default=None, help="把结果写成 JSON")
    args = parser.parse_args()

    module = _bootstrap()
    from fastapi.testclient import TestClient

    client = TestClient(module.app)
    task_id = _ingest(client, module)

    # 预热：jieba 首次加载词典约 1.2s、BM25 首次建索引也在首问里，
    # 不预热会把一次性成本算到 bm25 的均值上，看起来像「稀疏路很慢」。
    for mode in MODES:
        _retrieve(client, "预热查询", mode, args.k)

    report: dict[str, Any] = {
        "taskId": task_id,
        "k": args.k,
        "chunkSize": 180,
        "overlap": 30,
        "embeddingProvider": os.environ.get("AI_PROVIDER", "mock"),
        "corpus": sorted(path.name for path in DATA.glob("*.md")),
        "modes": list(MODES),
        "cases": [],
        "summary": {},
    }

    for question, expect_doc, case_id in CASES:
        row: dict[str, Any] = {"id": case_id, "question": question, "expectDoc": expect_doc, "runs": {}}
        for mode in MODES:
            row["runs"][mode] = _retrieve(client, question, mode, args.k)
        report["cases"].append(row)

    # 汇总：hit@k / top-1 / MRR / 平均耗时 / 平均首条分数
    # hit@k 在 k=3、6 份语料时容易饱和（各档都 6/6），真正能区分强弱的是
    # 「正确片段排在第几位」：top-1 命中率与 MRR（平均倒数排名）。
    for mode in MODES:
        hits = 0
        top1 = 0
        reciprocal_ranks = []
        latencies = []
        top_scores = []
        for case in report["cases"]:
            run = case["runs"][mode]
            titles = run["doc_titles"]
            if case["expectDoc"] in titles:
                hits += 1
                rank = titles.index(case["expectDoc"]) + 1
                reciprocal_ranks.append(1.0 / rank)
                if rank == 1:
                    top1 += 1
            else:
                reciprocal_ranks.append(0.0)
            latencies.append(run["elapsed_ms"])
            top_scores.append(run["scores"][0] if run["scores"] else 0.0)
        total = len(report["cases"])
        report["summary"][mode] = {
            "hitAtK": f"{hits}/{total}",
            "hitRate": round(hits / total, 4),
            "top1": f"{top1}/{total}",
            "mrr": round(statistics.fmean(reciprocal_ranks), 4),
            "avgLatencyMs": round(statistics.fmean(latencies), 2),
            "avgTopScore": round(statistics.fmean(top_scores), 6),
        }

    print(f"语料 {len(report['corpus'])} 份，问题 {len(CASES)} 个，k={args.k}，task={task_id}")
    provider = report["embeddingProvider"]
    print(f"embedding provider = {provider}" + (
        "（mock 向量是按 hash 生成的，dense 档不具备语义意义；"
        "要看真实效果请设 AI_PROVIDER=real 并给 EMBEDDING_* 变量）"
        if provider != "real" else ""
    ))
    print()
    header = f"{'case':<16}{'expect':<26}" + "".join(f"{mode:<10}" for mode in MODES)
    print(header)
    print("-" * len(header))
    for case in report["cases"]:
        cells = []
        for mode in MODES:
            run = case["runs"][mode]
            cells.append(("✓" if case["expectDoc"] in run["doc_titles"] else "✗") + f"{run['elapsed_ms']:.0f}ms")
        print(f"{case['id']:<16}{case['expectDoc']:<26}" + "".join(f"{cell:<10}" for cell in cells))

    print()
    print(f"{'mode':<8}{'hit@k':<9}{'top-1':<9}{'MRR':<9}{'平均耗时':<12}{'首条均分'}")
    for mode in MODES:
        s = report["summary"][mode]
        print(
            f"{mode:<8}{s['hitAtK']:<9}{s['top1']:<9}{s['mrr']:<9.4f}"
            f"{s['avgLatencyMs']:>7.2f}ms   {s['avgTopScore']:.4f}"
        )

    print("\n各问题 top-3 明细：")
    for case in report["cases"]:
        print(f"\n[{case['id']}] {case['question']}")
        for mode in MODES:
            run = case["runs"][mode]
            detail = ", ".join(
                f"{chunk}@{score:.3f}" for chunk, score in zip(run["chunk_ids"], run["scores"])
            )
            print(f"  {mode:<7} {detail}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
