"""检索质量评测：Recall@K / MRR / nDCG@K。

为什么要这个脚本：简历上写「混合检索 + RRF 融合」不如写「Recall@5 从 0.62 → 0.81」。
本脚本直接调 Python 服务的 /internal/v1/retrieve，用 assets/eval/questions.csv 的
「证据文件」列作为 ground truth，算出可写进简历的硬指标。

判定口径：一个 citation 命中，当且仅当它所属的文档文件名出现在该题的「证据文件」列里
（多文档题任一命中即算）。因为 CSV 的粒度是「文件」而不是「chunk」，
Recall@K 衡量的是「前 K 个引用里能否找到正确文件」。

用法（服务需已在 8000 运行）::

    python tests/eval/retrieval_metrics.py
    python tests/eval/retrieval_metrics.py --k 1 3 5 10
    python tests/eval/retrieval_metrics.py --mode hybrid --json out.json
    python tests/eval/retrieval_metrics.py --modes dense sparse hybrid
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "assets" / "eval" / "questions.csv"
TOKEN_FILE = REPO_ROOT / "test-artifacts" / "p7-env.json"
BASE = "http://127.0.0.1:8000/internal/v1"

# 检索档位：dense=纯向量, sparse=纯BM25, hybrid=混合+RRF, hybrid_rerank=混合+重排
# 真实档位名来自 app/services/ingest.py 的 retrieve()：
#   dense  = 纯向量
#   bm25   = 纯稀疏（BM25）
#   rrf    = 双路 RRF 融合（不精排）
#   hybrid = 双路 RRF + 精排（默认最优档）
# 注意不要写成 sparse/hybrid_rerank，服务端认不出会静默回落默认档，
# 结果就是四档指标完全一样（这个坑踩过）。
ALL_MODES = ["dense", "bm25", "rrf", "hybrid"]


def load_token() -> str:
    if not TOKEN_FILE.exists():
        raise SystemExit(f"缺 {TOKEN_FILE}，先跑一次 deploy/start-backend.bat 生成")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["INTERNAL_TOKEN"]


def load_questions(path: Path) -> list[dict]:
    raw = io.open(path, encoding="utf-8-sig").read()
    rows = list(csv.DictReader(io.StringIO(raw)))
    out = []
    for r in rows:
        evidence = (r.get("证据文件") or "").strip()
        # 「无」表示该题不依赖资料（例如寒暄），不计入检索评测
        if not evidence or evidence == "无":
            continue
        # 多文档题用 、或 ｜ 分隔
        files = [f.strip() for f in evidence.replace("、", "|").split("|") if f.strip()]
        out.append({
            "code": r.get("编号", ""),
            "type": r.get("类型", ""),
            "question": r.get("问题", ""),
            "files": files,
        })
    return out


def post_json(url: str, payload: dict, token: str,
              user_id: int = 6, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Internal-Token", token)
    # Python 侧 require_user_id 依赖这个头做数据隔离，缺了会 40001
    req.add_header("X-User-Id", str(user_id))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"HTTP {exc.code} {url}\n{body}")


def citation_file(c: dict) -> str:
    """从 citation 里取出所属文件名，用于和 CSV 的「证据文件」比对。

    实际响应字段是 doc_title（见 /internal/v1/retrieve 的 citations）。
    注意全库摘要的 doc_id 是 __summary__、doc_title 是「全库摘要」，
    它不属于任何单个源文件，比对时不会命中任何「证据文件」，这是正确的。
    """
    for key in ("doc_title", "file_name", "fileName", "doc_name", "source", "title", "name"):
        v = c.get(key)
        if isinstance(v, str) and v.strip():
            return os.path.basename(v.strip())
    # 有些实现把文件名放在 doc_id 里
    d = c.get("doc_id") or c.get("docId")
    if isinstance(d, str):
        return os.path.basename(d)
    return ""


def _normalize(name: str) -> str:
    """把文件名/标题归一化后用于比对。

    坑：同一条切片在两次索引里 doc_title 可能是「04_期刊与工具书.md」（原始文件名），
    也可能是「星河读书会期刊与工具书借阅规则」（H1 标题）——取决于该文档是解析自
    上传文件还是重建索引。直接字符串包含会漏判，所以这里：
      1. 去掉扩展名与序号码前缀（01_、B00_ 等）
      2. 去掉空白和标点
    再做双向包含判断。
    """
    import re
    s = (name or "").strip()
    s = re.sub(r"\.[A-Za-z0-9]+$", "", s)          # 去扩展名
    s = re.sub(r"^[0-9A-Za-z]{1,4}[_-]", "", s)     # 去 01_ / B00_ 前缀
    s = re.sub(r"[\s\-_/\\]+", "", s)            # 去空白与分隔符
    return s.lower()


def _is_hit(fname: str, files: list[str]) -> bool:
    """判断一个 citation 是否命中 ground truth 里的任一证据文件。"""
    a = _normalize(fname)
    if not a:
        return False
    for f in files:
        b = _normalize(f)
        if not b:
            continue
        # 双向包含：既覆盖「标题含文件名关键词」，也覆盖「文件名更短」
        if a == b or b in a or a in b:
            return True
    return False


def evaluate_one(question: str, files: list[str], k: int, mode: str,
                 token: str, user_id: int) -> dict:
    """返回该题的 rank（第一个正确答案的名次，1-based；未命中为 0）。"""
    payload = {"question": question, "k": k, "list_mode": True}
    url = f"{BASE}/retrieve" + (f"?retrieval_mode={mode}" if mode else "")
    resp = post_json(url, payload, token, user_id=user_id)
    citations = (resp.get("data") or {}).get("citations") or []

    first_hit = 0
    hit_files = []
    for idx, c in enumerate(citations, start=1):
        fname = citation_file(c)
        if _is_hit(fname, files):
            if first_hit == 0:
                first_hit = idx
            hit_files.append(fname)

    return {
        "rank": first_hit,
        "returned": len(citations),
        "hit_files": hit_files[:3],
    }


def dcg(rels: list[int], k: int) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def summarize(records: list[dict], ks: list[int]) -> dict:
    n = len(records)
    if n == 0:
        return {}
    out = {"n": n}
    for k in ks:
        hit = sum(1 for r in records if 0 < r["rank"] <= k)
        out[f"Recall@{k}"] = round(hit / n, 4)
        # nDCG@k：二值相关，单个正确答案
        nd = 0.0
        for r in records:
            rels = [1 if r["rank"] == i + 1 else 0 for i in range(k)]
            ideal = dcg([1] + [0] * (k - 1), k)
            nd += dcg(rels, k) / ideal if ideal else 0.0
        out[f"nDCG@{k}"] = round(nd / n, 4)
    # MRR：只看第一个正确命中的倒数排名
    mrr = sum(1.0 / r["rank"] for r in records if r["rank"] > 0) / n
    out["MRR"] = round(mrr, 4)
    out["Miss"] = sum(1 for r in records if r["rank"] == 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--k", type=int, nargs="+", default=[1, 3, 5, 10])
    ap.add_argument("--modes", nargs="+", default=["hybrid"],
                    help=f"可选 {'/'.join(ALL_MODES)}；传 all 跑全部档位对比")
    ap.add_argument("--json", help="把逐题明细写到这个路径")
    ap.add_argument("--user-id", type=int, default=6)
    args = ap.parse_args()

    token = load_token()
    questions = load_questions(Path(args.csv))
    modes = ALL_MODES if args.modes == ["all"] else args.modes
    max_k = max(args.k)

    print(f"题目 {len(questions)} 道（已剔除无证据文件题），K={args.k}")
    print(f"服务 {BASE}，user_id={args.user_id}\n")

    all_report = {}
    for mode in modes:
        records = []
        print(f"── 档位 {mode} " + "─" * 40)
        for q in questions:
            try:
                r = evaluate_one(q["question"], q["files"], max_k, mode, token, args.user_id)
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"  [{q['code']}] 调用失败: {exc}")
                r = {"rank": 0, "returned": 0, "hit_files": []}
            r.update({"code": q["code"], "type": q["type"],
                      "question": q["question"], "expect": q["files"]})
            records.append(r)
            mark = "[HIT]" if 0 < r["rank"] <= max_k else "[MISS]"
            print(f"  {mark} [{q['code']}] rank={r['rank'] or '-'} "
                  f"expect={','.join(q['files'])[:40]}")

        summary = summarize(records, args.k)
        all_report[mode] = {"summary": summary, "records": records}
        print(f"\n  汇总: " + "  ".join(f"{k}={v}" for k, v in summary.items()))
        print()

    if len(modes) > 1:
        print("=" * 62)
        print(f"{'档位':<16}" + "".join(f"{f'R@{k}':>9}" for k in args.k) + f"{'MRR':>9}{'Miss':>7}")
        print("-" * 62)
        for mode in modes:
            s = all_report[mode]["summary"]
            line = f"{mode:<16}"
            line += "".join(f"{s.get(f'Recall@{k}', 0):>9.3f}" for k in args.k)
            line += f"{s.get('MRR', 0):>9.3f}{s.get('Miss', 0):>7}"
            print(line)
        print("=" * 62)

    if args.json:
        Path(args.json).write_text(
            json.dumps(all_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n逐题明细已写入 {args.json}")

    return 0


if __name__ == "__main__":
    # Windows 控制台默认 GBK，中文/符号可能编码失败，这里兜住
    try:
        raise SystemExit(main())
    except UnicodeEncodeError:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
        raise SystemExit(main())
