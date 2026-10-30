"""批量对照测试：10 题 × 两模式 + 关键词初判 + 统计 + CSV 导出（对应 F9 / 任务5）。"""
from __future__ import annotations

import csv
import threading
from datetime import datetime
from typing import Any

from . import chat, judging, session
from .settings import AppError, EXPORT_DIR

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "stage": "idle",     # idle / running / done / error
    "done": 0,
    "total": 0,
    "rows": [],
    "stats": {"total": 0, "direct": 0, "rag": 0},
    "error": "",
    "export_path": "",
    "current": "",
}

CSV_HEADER = ["题号", "类型", "问题", "direct回答", "direct初判", "rag回答", "rag初判", "rag来源片段"]


def _one(question: str, mode: str, k: int) -> dict[str, Any]:
    """单题单模式：先清空会话，避免上一题污染。"""
    session.new_session()
    return chat.answer_once(question, mode, k, log=False)


def run_batch(k: int | None = None) -> dict[str, Any]:
    """同步执行全部题目（供命令行/自检使用）。"""
    items = judging.load_eval_set()
    use_k = k if k is not None else session.current_k()
    rows: list[dict[str, Any]] = []
    passed_direct = passed_rag = 0
    for item in items:
        direct_result = _one(item["question"], "direct", use_k)
        rag_result = _one(item["question"], "rag", use_k)
        direct_ok = judging.judge(direct_result["answer"], item["keywords"])
        rag_ok = judging.judge(rag_result["answer"], item["keywords"])
        passed_direct += int(direct_ok)
        passed_rag += int(rag_ok)
        rows.append({
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "direct_answer": direct_result["answer"],
            "direct_pass": direct_ok,
            "rag_answer": rag_result["answer"],
            "rag_pass": rag_ok,
            "rag_sources": "、".join(
                f'{card["chunk_id"]}({card["source"]})' for card in rag_result["citations"]
            ),
            "keywords": item["keywords"],
            "answer_points": item["answer_points"],
            "evidence": item["evidence"],
        })
    session.new_session()
    stats = {"total": len(rows), "direct": passed_direct, "rag": passed_rag}
    return {"rows": rows, "stats": stats, "k": use_k}


def run_batch_async(k: int | None = None) -> None:
    """后台线程跑批量，前端轮询 /api/batch/progress。"""
    if _STATE["stage"] == "running":
        raise AppError("正在运行对照测试，请等待当前任务完成。")

    def worker() -> None:
        _STATE.update({"stage": "running", "done": 0, "total": 0, "rows": [], "error": "", "export_path": "", "current": ""})
        try:
            items = judging.load_eval_set()
            use_k = k if k is not None else session.current_k()
            _STATE["total"] = len(items) * 2
            rows: list[dict[str, Any]] = []
            passed_direct = passed_rag = 0
            for item in items:
                _STATE["current"] = f'{item["id"]} {item["question"]}'
                direct_result = _one(item["question"], "direct", use_k)
                _STATE["done"] += 1
                rag_result = _one(item["question"], "rag", use_k)
                _STATE["done"] += 1
                direct_ok = judging.judge(direct_result["answer"], item["keywords"])
                rag_ok = judging.judge(rag_result["answer"], item["keywords"])
                passed_direct += int(direct_ok)
                passed_rag += int(rag_ok)
                rows.append({
                    "id": item["id"],
                    "type": item["type"],
                    "question": item["question"],
                    "direct_answer": direct_result["answer"],
                    "direct_pass": direct_ok,
                    "rag_answer": rag_result["answer"],
                    "rag_pass": rag_ok,
                    "rag_sources": "、".join(
                        f'{card["chunk_id"]}({card["source"]})' for card in rag_result["citations"]
                    ),
                    "keywords": item["keywords"],
                    "answer_points": item["answer_points"],
                    "evidence": item["evidence"],
                })
            session.new_session()
            _STATE.update({
                "stage": "done",
                "rows": rows,
                "stats": {"total": len(rows), "direct": passed_direct, "rag": passed_rag},
                "current": "",
            })
        except AppError as exc:
            _STATE.update({"stage": "error", "error": str(exc)})
        except Exception as exc:                     # noqa: BLE001
            _STATE.update({"stage": "error", "error": f"对照测试失败：{exc}"})

    threading.Thread(target=worker, daemon=True).start()


def batch_state() -> dict[str, Any]:
    return dict(_STATE)


def export_csv(rows: list[dict[str, Any]] | None = None) -> str:
    """导出结果表：UTF-8 BOM，Excel 直接双击不乱码。"""
    rows = rows if rows is not None else _STATE["rows"]
    if not rows:
        raise AppError("还没有对照测试结果，请先运行测试。")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = EXPORT_DIR / f"对照测试_{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow([
                row["id"],
                row["type"],
                row["question"],
                row["direct_answer"],
                "通过" if row["direct_pass"] else "未通过",
                row["rag_answer"],
                "通过" if row["rag_pass"] else "未通过",
                row["rag_sources"],
            ])
    _STATE["export_path"] = str(path)
    return str(path)
