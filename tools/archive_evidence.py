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
import re
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


# docker inspect 的 `Labels` 是一长串 `k=v` 用逗号连接。其中几类对读者没意义，却让一行
# JSON 膨胀到 1500 字节：内容哈希（config-hash / image digest）换次构建就变，镜像自带的
# description 是整段 Ubuntu 宣传语。剥掉它们，保留 service/project/version/ports ——
# 那些才是「这个容器属于哪套 compose」的证据。
#
# 不能按逗号 split：description 的值里本身含逗号（"…clouds, to all your…"）。这里用
# 「逗号后面紧跟 `key=`」作为条目边界，description 内部的逗号后面是普通单词，不会被切开。
_LABEL_BOUNDARY = re.compile(r",(?=[A-Za-z0-9_.\-/]+=)")
LABEL_DROP = (
    "com.docker.compose.config-hash",
    "com.docker.compose.image",
    "org.opencontainers.image.description",
    "org.opencontainers.image.created",
    "desktop.docker.io/binds/0/Source",
    "maintainer",
)


def strip_labels(node: Any) -> int:
    """就地剥掉 `Labels` 里无用的条目，返回删掉的条数。

    只处理形如 ``"Labels": "k=v,k=v"`` 的 docker inspect 输出；其余字符串原样保留。
    """
    removed = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Labels" and isinstance(value, str) and "com.docker.compose." in value:
                parts = _LABEL_BOUNDARY.split(value)
                kept = [
                    part
                    for part in parts
                    if part.split("=", 1)[0].strip() not in LABEL_DROP
                ]
                removed += len(parts) - len(kept)
                node[key] = ",".join(kept)
            else:
                removed += strip_labels(value)
    elif isinstance(node, list):
        for item in node:
            removed += strip_labels(item)
    return removed


def archive_payload(path: Path) -> tuple[str, int, int]:
    """读取并清洗一份报告，返回（清洗后的 JSON 文本，路径占位次数，剥掉的 label 条数）。

    清洗后必须仍能被 `json.loads` 解析 —— 占位符里没有反斜杠，不会破坏转义。
    只有真的剥了 label 的文件才重新序列化；其余保持原始排版，diff 才看得出改了什么。
    """
    text, count = scrub(path.read_text(encoding="utf-8"))
    data = json.loads(text)
    removed = strip_labels(data)
    if removed:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        json.loads(text)
    return text, count, removed


def summarize(path: Path, data: Any) -> str:
    """给索引表写一句「这份报告说明了什么」，全部取自文件本身，不猜。"""
    name = path.name
    if not isinstance(data, dict):
        return "—"
    if name.startswith("backend-gate-") and "pass" in data:
        verdict = "pass" if data["pass"] else "FAIL"
        gates = data.get("gates")
        if isinstance(gates, (dict, list)):
            line = f"{verdict} · {len(gates)} 个门禁"
        else:
            line = verdict
        # backend-gate-all.json 是 run_all.py 的产物，而 J3/J5 要 mock、其余要 real，
        # 两档互斥 —— 单次调用必然只覆盖一部分阶段。不标注就会被读成全量通过。
        covered = data.get("coveredStages")
        if data.get("partial") and isinstance(covered, list):
            line += f"（仅 {'/'.join(covered)}，非全量）"
        return line
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
        "## 清洗规则",
        "",
        "归档前只做两件事，其余内容原样保留：",
        "",
        "1. **本机绝对路径占位** —— `D:\\VM1\\Xiaoyi_RAG_bookstore` → `<repo>`、`D:\\python` → `<python>`、"
        "`C:\\Users\\limingjie` → `<home>`、`D:\\IDEA` → `<idea>`、`D:\\MYSQL` → `<mysql>`。",
        "2. **剥掉 docker inspect 的无用 label** —— `com.docker.compose.config-hash`、"
        "`com.docker.compose.image`（镜像 digest）、`org.opencontainers.image.description`"
        "（整段镜像宣传语）、`maintainer`、`desktop.docker.io/binds/0/Source`。"
        "这些换次构建就变，留着只会让一行 JSON 膨胀到 1500 字节。"
        "`service` / `project` / `version` / `depends_on` / `ports` 保留 —— 它们才是"
        "「这个容器属于哪套 compose」的证据。",
        "",
        "## 关于 `backend-gate-all.json`",
        "",
        "这份报告由 `test/run_all.py` 写出。J3/J5 断言的是 mock provider 的确定性输出，"
        "必须 `AI_MOCK=true`；其余阶段要真实链路，必须 `AI_MOCK=false`。两档互斥，"
        "**单次调用跑不出全量**，所以 `run_all.py` 默认把多轮结果合并进同一份文件，"
        "每条 gate 带 `ranAt` 标明属于哪一轮。`partial: true` 表示还有阶段没被任何一轮覆盖，"
        "此时索引的结论列会标注「仅 X/Y，非全量」。",
        "",
        "## 归档清单",
        "",
        "| 文件 | 大小 | 结论 | 内容 SHA256 前 16 位 |",
        "| --- | ---: | --- | --- |",
    ]
    for path in files:
        # 哈希取「归档后的内容」（本机路径已占位、无用 label 已剥），否则 --check 与索引对不上。
        archived, _, _ = archive_payload(path)
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
        expected, _, _ = archive_payload(src)
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
    stripped = 0
    for src in files:
        text, count, removed = archive_payload(src)  # 解析失败就抛，不把坏文件写过去
        dst = TARGET / src.name
        dst.write_text(text, encoding="utf-8")
        total += dst.stat().st_size
        scrubbed += count
        stripped += removed
        notes = []
        if count:
            notes.append(f"路径占位 {count}")
        if removed:
            notes.append(f"剥离 label {removed}")
        suffix = f"  ({'，'.join(notes)})" if notes else ""
        print(f"  {src.name:<40} {dst.stat().st_size:>8,} B{suffix}")

    index = TARGET / INDEX_NAME
    index.write_text(render_index(files), encoding="utf-8")
    print(f"\n归档 {len(files)} 份，共 {total:,} B -> {TARGET.relative_to(ROOT)}")
    if scrubbed:
        print(f"本机绝对路径已占位：{scrubbed} 处")
    if stripped:
        print(f"docker label 已剥离：{stripped} 条（config-hash / image digest / 镜像描述）")
    print(f"索引 {index.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验，不复制")
    args = parser.parse_args()
    return check() if args.check else archive()


if __name__ == "__main__":
    sys.exit(main())
