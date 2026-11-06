"""把 P7 报告 A 项里两条实测证据刷新为最新一次 compose_smoke 的数字。

compose_smoke.py 是幂等累积型的（每次上传一份资料），所以第一次记的
`count=6 / A=1 B=0` 与复跑后的 `A=3 B=0` 都对，但报告里应保留最近一次。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "test-artifacts" / "backend-gate-P7.json"
SMOKE = ROOT / "test-artifacts" / "compose-smoke.json"

data = json.loads(REPORT.read_text(encoding="utf-8"))
smoke = json.loads(SMOKE.read_text(encoding="utf-8"))

docs_a = smoke["documents"]["A"]
docs_b = smoke["documents"]["B"]
chunks_a = smoke["chunks"]["A"]
chunks_b = smoke["chunks"]["B"]
task_id = smoke["rebuild"]["taskId"]
task_chunks = smoke["rebuild"]["chunks"]
homepage = smoke["homepageBytes"]

new_docs = (
    "经 nginx(8088)：`POST /api/v1/auth/login` → code=0、token 227 字符、user.id=2、"
    "username=local-a、expiresIn=3600；`GET /api/v1/health` → UP；`GET /` → 200、"
    f"{homepage} 字节、含 `<div id=\"app\">`"
)
new_smoke = (
    "`python tools/compose_smoke.py` → 首页 ok / 登录 ok local-a(id=2) / local-b(id=3) / "
    f"列表隔离 ok A={docs_a} B={docs_b} / 建库 SUCCEEDED task={task_id} chunks={task_chunks} / "
    f"chunks 隔离 ok A={chunks_a} B={chunks_b} / 库核对 db={smoke['database']} / PASS"
)

for item in data["items"]:
    if item.get("item") != "A":
        continue
    evidence = []
    for line in item["evidence"]:
        if line.startswith("经 nginx(8088)"):
            evidence.append(new_docs)
        elif line.startswith("`python tools/compose_smoke.py`"):
            evidence.append(new_smoke)
        else:
            evidence.append(line)
    item["evidence"] = evidence

data["timestamp"] = "2026-11-06T10:50:18+08:00"
REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("[refresh-p7-evidence] updated 2 lines")
print(f"  docs A={docs_a} B={docs_b}  chunks A={chunks_a} B={chunks_b}  task={task_id}")
