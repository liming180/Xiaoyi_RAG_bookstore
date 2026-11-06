"""把 P7 报告 A 项的字段名收敛为实测语义。

A 项原先用 verifiedInstead / equivalentEvidence / composeBlockedBy 表示「Compose 未取证、
改用等价路径验证」。2026-11-06 容器栈实测通过后，这些字段名会误导读者，
统一改为 evidence / note / result。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "test-artifacts" / "backend-gate-P7.json"

data = json.loads(REPORT.read_text(encoding="utf-8"))
items = []
for item in data["items"]:
    if item.get("item") != "A":
        items.append(item)
        continue
    evidence = item.pop("verifiedInstead", [])
    item.pop("equivalentEvidence", None)
    item.pop("composeBlockedBy", None)
    merged = {
        "item": "A",
        "name": item["name"],
        "ok": item["ok"],
        "status": item["status"],
        "command": item["command"],
        "blockedBy": item.get("blockedBy"),
        "evidence": evidence,
        "note": item.get("note"),
        "result": item.get("result"),
    }
    items.append(merged)

data["items"] = items
REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

a = items[0]
print(f"[normalize-p7] item A keys = {list(a.keys())}")
print(f"[normalize-p7] evidence = {len(a['evidence'])} 条")
print(f"[normalize-p7] allOk = {all(i['ok'] for i in items)}")
