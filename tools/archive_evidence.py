"""把 `test-artifacts/` 里的门禁报告归档进版本库。

为什么需要这一步：`test-artifacts/` 被 `.gitignore:14` 忽略（里面混着 147 MB 的 pip 依赖
`_pm/`、几百 MB 的 storage 与截图），但文档里有大量指向报告的反引号路径与 Markdown 链接。
不留档的后果是链接全部失效、文档里的数字失去可追溯性。

这个工具只挑**小体积、可公开**的 JSON，落到 `docs/03-架构评审/evidence/`：

* 排除 `p7-env.json`（含 `AUTH_JWT_SECRET`、`INTERNAL_TOKEN`、两个 bootstrap 口令）、
  `local-mysql-public.json`（含两个 bootstrap 口令）、`p7-pids.json`（本机进程号，无意义）；
* `local-mysql-verify.json` 里的 `passwordHashPrefix` 只是 `$2a$12$` 这样的 bcrypt 前缀，
  保留 —— 它恰好是「口令没明文落库」的证据；
* 其余 `backend-gate-*.json`、`a3-compare-*.json`、`p7-*.json`、`docker-deploy-*.json`、
  `compose-smoke.json` 原样复制。

用法（仓库根）：

    python tools/archive_evidence.py            # 复制 + 重写 index.md
    python tools/archive_evidence.py --check    # 只校验已归档的是否落后于 test-artifacts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "test-artifacts"
TARGET = ROOT / "docs" / "03-架构评审" / "evidence"

# 这些文件含真实凭据或本机进程号，一律不进版本库。
EXCLUDED = {
    "p7-env.json",
    "local-mysql-public.json",
    "p7-pids.json",
}

# 归档文件名前缀白名单：只收报告类，不收日志、storage、截图。
PREFIXES = ("backend-gate-", "a3-compare-", "docker-deploy-", "p7-", "compose-smoke", "local-mysql-")

INDEX_NAME = "index.md"


def selected() -> list[Path]:
    """列出该归档的源文件：根目录下、命中前缀、未被排除。"""
    if not SOURCE.is_dir():
        return []
    picked = []
    for path in sorted(SOURCE.glob("*.json")):
        if path.name in EXCLUDED:
            continue
        if not path.name.startswith(PREFIXES):
            continue
        picked.append(path)
    return picked


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def payload(path: Path) -> Any:
    """读 JSON；解析失败直接抛出，不把坏文件归档。"""
    return json.loads(path.read_text(encoding="utf-8"))


# 归档前把本机绝对路径换成占位符：这些路径对别人没意义，还会泄露目录结构。
# JSON 里反斜杠是转义的（`D:\\VM1\\...`），所以每个模式都要覆盖「转义」与「原样」两种写法。
SCRUB: tuple[tuple[str, str], ...] = (
    ("D:\\\\VM1\\\\Xiaoyi_RAG_bookstore", "<repo>"),
    ("D:\\VM1\\Xiaoyi_RAG_bookstore", "<repo>"),
    ("D:\\\\python", "<python>"),
    ("D:\\python", "<python>"),
    ("C:\\\\Users\\\\limingjie", "<home>"),
    ("C:\\Users\\limingjie", "<home>"),
    ("D:\\\\IDEA", "<idea>"),
    ("D:\\IDEA", "<idea>"),
    ("D:\\\\MYSQL", "<mysql>"),
    ("D:\\MYSQL", "<mysql>"),
)


def scrub(text: str) -> tuple[str, int]:
    """替换本机绝对路径，返回（新文本，替换次数）。"""
    total = 0
    for old, new in SCRUB:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            total += count
    return text, total


def archive_payload(path: Path) -> tuple[str, int]:
    """读取并清洗一份报告，返回（清洗后的 JSON 文本，替换次数）。

    清洗后必须仍能被 `json.loads` 解析 —— 占位符里没有反斜杠，不会破坏转义。
    """
    text, count = scrub(path.read_text(encoding="utf-8"))
    json.loads(text)
    return text, count


def summarize(path: Path, data: Any) -> str:
    """给索引表写一句「这份报告说明了什么」，全部取自文件本身，不猜。"""
    name = path.name
    if not isinstance(data, dict):
        return "—"
    if name.startswith("backend-gate-") and "pass" in data:
        verdict = "pass" if data["pass"] else "FAIL"
        gates = data.get("gates")
        if isinstance(gates, dict):
            return f"{verdict} · {len(gates)} 个门禁"
        if isinstance(gates, list):
            return f"{verdict} · {len(gates)} 个门禁"
        return verdict
    # a3-compare-*.json：四档对照，取 hybrid 与 dense 的 MRR 对比
    if name.startswith("a3-compare-") and isinstance(data.get("summary"), dict):
        summary = data["summary"]
        dense = summary.get("dense", {}).get("mrr")
        hybrid = summary.get("hybrid", {}).get("mrr")
        cases = len(data.get("cases") or [])
        return f"{cases} 题 · dense MRR {dense} / hybrid MRR {hybrid}"
    # p7-evidence.json：逐项 A–G，统计 ok 条数
    if isinstance(data.get("items"), list):
        items = data["items"]
        good = sum(1 for item in items if isinstance(item, dict) and item.get("ok"))
        return f"{good}/{len(items)} 项 ok"
    if "ok" in data:
        return "ok" if data["ok"] else "FAIL"
    if "pass" in data:
        return "pass" if data["pass"] else "FAIL"
    return "—"


def render_index(files: list[Path]) -> str:
    lines = [
        "# 门禁报告归档",
        "",
        "> 本目录由 `tools/archive_evidence.py` 生成，**不要手工编辑**。",
        "> 源目录 `test-artifacts/` 被 `.gitignore` 忽略（内含 147 MB 依赖与数百 MB storage），",
        "> 这里只留小体积、可公开的 JSON，让文档里的数字可被核对。",
        "",
        "重新生成：",
        "",
        "```powershell",
        "python tools\\write_a3_report.py     # 或对应阶段自己的报告工具",
        "python tools\\archive_evidence.py",
        "```",
        "",
        "## 归档清单",
        "",
        "| 文件 | 大小 | 结论 | 内容 SHA256 前 16 位 |",
        "| --- | ---: | --- | --- |",
    ]
    for path in files:
        # 哈希取「归档后的内容」（本机路径已占位），否则 --check 与索引对不上。
        archived, _ = archive_payload(path)
        lines.append(
            f"| `{path.name}` | {len(archived.encode('utf-8')):,} B | "
            f"{summarize(path, payload(path))} | `{hashlib.sha256(archived.encode('utf-8')).hexdigest()[:16]}` |"
        )
    lines += [
        "",
        "## 未归档的文件",
        "",
        "| 文件 | 原因 |",
        "| --- | --- |",
        "| `p7-env.json` | 含 `AUTH_JWT_SECRET`、`INTERNAL_TOKEN` 与两个 bootstrap 口令 |",
        "| `local-mysql-public.json` | 含两个 bootstrap 口令 |",
        "| `p7-pids.json` | 本机进程号，换机器即失效 |",
        "| `_pm/`、`*-storage/`、`screenshots/` | 依赖与二进制产物，体积过大 |",
        "",
        "## 校验",
        "",
        "`--check` 会比对源目录与归档目录的哈希；源报告重跑后没重新归档时会报出来：",
        "",
        "```powershell",
        "python tools\\archive_evidence.py --check",
        "```",
        "",
    ]
    return "\n".join(lines)


def check() -> int:
    """比对归档与源（按清洗后的内容）；返回 0 表示一致。"""
    stale: list[str] = []
    missing: list[str] = []
    for src in selected():
        dst = TARGET / src.name
        if not dst.exists():
            missing.append(src.name)
            continue
        expected, _ = archive_payload(src)
        if expected != dst.read_text(encoding="utf-8"):
            stale.append(src.name)
    if missing:
        print(f"未归档：{', '.join(missing)}")
    if stale:
        print(f"与源不一致（源已重跑，需重新归档）：{', '.join(stale)}")
    if not missing and not stale:
        print(f"归档一致：{len(selected())} 份报告")
        return 0
    return 1


def archive() -> int:
    files = selected()
    if not files:
        print(f"没有可归档的报告：{SOURCE} 下未找到匹配前缀的 JSON")
        return 1
    TARGET.mkdir(parents=True, exist_ok=True)

    # 先清掉本工具上次生成、但这次源里已经不存在的文件，避免归档目录长霉。
    keep = {path.name for path in files} | {INDEX_NAME}
    for old in TARGET.glob("*.json"):
        if old.name not in keep:
            old.unlink()
            print(f"  移除过期归档 {old.name}")

    total = 0
    scrubbed = 0
    for src in files:
        text, count = archive_payload(src)  # 解析失败就抛，不把坏文件写过去
        dst = TARGET / src.name
        dst.write_text(text, encoding="utf-8")
        total += dst.stat().st_size
        scrubbed += count
        suffix = f"  (路径占位 {count})" if count else ""
        print(f"  {src.name:<40} {dst.stat().st_size:>8,} B{suffix}")

    index = TARGET / INDEX_NAME
    index.write_text(render_index(files), encoding="utf-8")
    print(f"\n归档 {len(files)} 份，共 {total:,} B -> {TARGET.relative_to(ROOT)}")
    if scrubbed:
        print(f"本机绝对路径已占位：{scrubbed} 处")
    print(f"索引 {index.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验，不复制")
    args = parser.parse_args()
    return check() if args.check else archive()


if __name__ == "__main__":
    sys.exit(main())
