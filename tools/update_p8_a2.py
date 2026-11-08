"""把 A2 的实测数字并入 P8 报告：更新受影响的门禁并新增 a2-real-rag 一项。

为什么要改 P8 而不是只留 A2 报告：P8 是「质量收口」的汇总报告，
`root-gates-real-provider` 与 `java-verify` 这两个数字在 A2 之后变了，
不刷新就会留下过期证据。脚本幂等，可重复跑。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P8 = ROOT / "test-artifacts" / "backend-gate-P8.json"

report = json.loads(P8.read_text(encoding="utf-8"))

by_key = {gate["key"]: gate for gate in report["gates"]}

real = by_key["root-gates-real-provider"]
real["command"] = (
    "cd test; NO_PROXY=127.0.0.1,localhost python -X utf8 -m pytest "
    "J0-contract J1-skeleton J2-crud J4-ingest J6-integration J7-isolation "
    "A1-ai-skeleton A2-rag -q"
)
real["counts"] = {"passed": 274, "skipped": 1, "failed": 0}
real["elapsed"] = "162.32s"
real["note"] = (
    "A2 落地后重跑：比 P8 首次的 246 多 28 条（A1 11 + A2 17）。"
    "skip 仍是 J1-skeleton/test_envelope_all_routes.py:106 参数集为空。"
)

java = by_key["java-verify"]
java["counts"] = {"testsPassed": 63, "failed": 0, "errors": 0, "skipped": 0}
java["detail"] = (
    "AuthServiceTest 11 / ChatServiceImplTest 8 / DocumentServiceImplTest 7 / "
    "ExperimentServiceTest 3 / FeedbackServiceTest 7 / IndexServiceImplTest 15 / "
    "TokenServiceTest 12"
)
java["note"] = (
    "A2 期间给 IndexServiceImplTest 补了 statusReportsEmbeddingModelFromManifest 与 "
    "statusFallsBackToTaskModelWhenManifestIsSilent 两条，61 → 63。"
)

snapshot = by_key["architecture-snapshot"]
snapshot["counts"] = {"lines": 284}
snapshot["note"] = (
    "A2 新增 4 个 Python 模块（splitter / embedder / pipeline / prompt）与 2 个测试文件后，"
    "server-ai 从 18 文件 924 行变成 22 文件 2178 行。"
)

mock = by_key["root-gates-mock-provider"]
mock["note"] = (
    "AI_MOCK=true 的 java 容器（8081，同 network / 同库 / 同 storage 卷），"
    "因为 J3/J5 依赖 MockAiClient 的 [fail] 标记与关键词打分。A2 之后重跑仍 55 passed。"
)

compose = by_key["compose-stack"]
compose["note"] = (
    compose["note"]
    + "；A2 之后 compose_smoke 复跑 PASS（docs A=4 / B=1、建库 9 片段、chunks A=9 / B=0）"
)

a2_gate = {
    "key": "a2-real-rag",
    "command": (
        "cd test && python -X utf8 -m pytest A2-rag -q；"
        "另跑 test-artifacts/_probe_a2_stack.py 走容器栈 + 智谱 embedding-3 + Milvus 3.0.0"
    ),
    "ok": True,
    "exitCode": 0,
    "counts": {"passed": 17, "failed": 0, "skipped": 0},
    "report": "test-artifacts/backend-gate-A2.json",
    "detail": (
        "切分 10 条（标题继承 / 偏移连续 / chunk_id 形状 / 投毒标记 / k 精确控制 / "
        "跨用户为空 / direct 无 retrieval 帧）+ 引用契约 7 条（Draft202012Validator "
        "拿 openapi-internal.yaml 校验真实响应）。"
    ),
    "note": (
        "真实链路：建库 chunks=8，top-3 为 D74-C001 0.6630 / D76-C002 0.5812 / "
        "D75-C001 0.5733，跨用户检索 0 条，SSE 回答带 [1] 标注与 3 行轨迹。"
        "CI 里只跑 A2 套件（进程内 mock provider + 内存向量库），不依赖外部 Milvus。"
    ),
}

if "a2-real-rag" not in by_key:
    # 插在 compose-stack 之前，让「代码质量」与「部署形态」分开
    index = next(i for i, gate in enumerate(report["gates"]) if gate["key"] == "compose-stack")
    report["gates"].insert(index, a2_gate)
else:
    by_key["a2-real-rag"].update(a2_gate)

limitations = report.get("knownLimitations", [])
extra = [
    "A2 的真实向量检索只在容器栈 + 本机 Milvus 上证过（test-artifacts/_probe_a2_stack.py，未进版本库）；CI 不启 Milvus，只验切分与引用契约。",
    "Milvus 3.0.0 默认 Bounded 一致性：写侧不 flush 时默认读看不到，本项目靠读侧 consistency_level='Strong' 规避，换 Milvus 版本要重验。",
    "分块默认值仍是 180/30，未按设计文档 §14.1 改 500/75：Java IndexServiceImpl.status() 的 needs_rebuild 判定与 J4 五处断言都钉死 180。",
]
for item in extra:
    if item not in limitations:
        limitations.append(item)
report["knownLimitations"] = limitations
report["timestamp"] = "2026-11-07T02:25:00+08:00"

P8.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"updated {P8}")
for gate in report["gates"]:
    print(f"  - {gate['key']}: ok={gate['ok']}")
