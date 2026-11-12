"""生成 test/fixtures/questions_t01_t10.json（由 assets/eval 下的两份 CSV 转出）。

输出结构（手册 §2.2 规定）::

    [{"id": "T01", "type": "单文档", "question": "...", "keywords": "...", "evidence": "..."}, ...]

`keywords` 保持 `keywords.csv` 的原始写法（组间 `|`、组内 `/`），
判分逻辑见 `frontend/src/mocks/state.ts` 的 `judge()`：
拆 `|` 得到若干组，每组拆 `/` 任一命中即该组通过，全部组通过才算 pass。

`evidence` 取自 `questions.csv` 的「证据文件」列，对应契约
`EvalQuestion.required = [id, type, question, keywords, evidence]`
（`docs/api/openapi-public.yaml:1884`）。

**type 的中英差异（J5 必须处理）**：CSV 用中文 `单文档 / 跨文档 / 库外`，
而契约 `EvalQuestion.type` 的 enum 是英文 `[single, cross, out]`
（`openapi-public.yaml:1894`）。本 fixture 是 CSV 的**逐字镜像**，故保留中文；
`GET /api/v1/eval/questions` 在 J5 实现时必须按 `TYPE_TO_CONTRACT` 转成英文再出参，
否则响应过不了契约校验。前端 mock（`frontend/src/mocks/data.ts`）同样用中文，
所以前端 `groupQuestions()` 的分组键也是中文，改动时要两头一起动。

数据源是 `assets/eval/`（J0 阶段从仓库根的 `questions.csv` / `eval/keywords.csv`
复制过来的**现行**路径）；仓库根那两份已随 v1 清理删除。

题量：T01–T13 共 13 题（J0 时是 10 题，后续补了 T11 期刊工具书 / T12 日期例外 /
T13 未核实留言三题，把 04/05/06 三份资料也纳入评测覆盖）。文件名沿用
`questions_t01_t10.json` 是手册 §2.2 写死的路径，不改名以免断引用。

用法::

    py -3.12 -X utf8 test/fixtures/_make_questions.py
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_CSV = REPO_ROOT / "assets" / "eval" / "questions.csv"
KEYWORDS_CSV = REPO_ROOT / "assets" / "eval" / "keywords.csv"
OUT = Path(__file__).resolve().parent / "questions_t01_t10.json"

# CSV 的中文类型 → 契约 EvalQuestion.type 的英文 enum（openapi-public.yaml:1894）。
# 本 fixture 保留 CSV 原文，转换留给 J5 的 listEvalQuestions 出参时做。
TYPE_TO_CONTRACT = {"单文档": "single", "跨文档": "cross", "库外": "out"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh)]


def main() -> None:
    questions = read_csv(QUESTIONS_CSV)
    keywords = {row["题号"].strip(): row["判分关键词"].strip() for row in read_csv(KEYWORDS_CSV)}

    items: list[dict[str, str]] = []
    missing: list[str] = []
    unknown_type: list[str] = []
    for row in questions:
        qid = (row.get("编号") or "").strip()
        if not qid:
            continue
        kw = keywords.get(qid, "")
        if not kw:
            missing.append(qid)
        qtype = (row.get("类型") or "").strip()
        if qtype not in TYPE_TO_CONTRACT:
            unknown_type.append(f"{qid}={qtype}")
        items.append(
            {
                "id": qid,
                "type": qtype,
                "question": (row.get("问题") or "").strip(),
                "keywords": kw,
                "evidence": (row.get("证据文件") or "").strip(),
            }
        )

    OUT.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"written {OUT} items={len(items)}")
    by_type: dict[str, int] = {}
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    print("类型分布：" + "、".join(f"{k} {v}" for k, v in by_type.items()))
    if missing:
        raise SystemExit(f"keywords.csv 缺少这些题号的关键词：{missing}")
    if unknown_type:
        raise SystemExit(f"这些题的「类型」不在 {list(TYPE_TO_CONTRACT)} 里：{unknown_type}")


if __name__ == "__main__":
    main()
