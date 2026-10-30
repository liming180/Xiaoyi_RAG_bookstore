"""判分：关键词初判 + 题目读取（对应 F9）。"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .settings import AppError, KEYWORDS_CSV, QUESTIONS_CSV


def judge(answer: str, keywords: str) -> bool:
    """组间 `|` 全命中、组内 `/` 命中其一（指导书原文规则）。"""
    if not keywords:
        return False
    text = answer or ""
    for group in keywords.split("|"):
        alternatives = [alt for alt in group.split("/") if alt]
        if not alternatives:
            continue
        if not any(alt in text for alt in alternatives):
            return False
    return True


def load_keywords(path: Path | None = None) -> dict[str, str]:
    path = path or KEYWORDS_CSV
    if not path.is_file():
        raise AppError(f"找不到判分关键词文件：{path.name}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    mapping = {}
    for row in rows:
        tid = (row.get("题号") or "").strip()
        kw = (row.get("判分关键词") or "").strip()
        if tid and kw:
            mapping[tid] = kw
    return mapping


def load_questions(path: Path | None = None) -> list[dict[str, str]]:
    path = path or QUESTIONS_CSV
    if not path.is_file():
        raise AppError(f"找不到题目文件：{path.name}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    questions = []
    for row in rows:
        tid = (row.get("编号") or "").strip()
        if not tid:
            continue
        questions.append({
            "id": tid,
            "type": (row.get("类型") or "").strip(),
            "question": (row.get("问题") or "").strip(),
            "answer_points": (row.get("答案要点") or "").strip(),
            "evidence": (row.get("证据文件") or "").strip(),
        })
    return questions


def load_eval_set() -> list[dict[str, Any]]:
    """把 questions.csv 与 eval/keywords.csv 按题号合并。"""
    keywords = load_keywords()
    items = []
    for question in load_questions():
        items.append(dict(question, keywords=keywords.get(question["id"], "")))
    missing = [item["id"] for item in items if not item["keywords"]]
    if missing:
        raise AppError(f"以下题目缺少判分关键词：{', '.join(missing)}")
    return items
