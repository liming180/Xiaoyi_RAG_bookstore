r"""从教师提供的示意网页中抽出 6 份资料，写入 data/。

用法：
    py -3.12 -X utf8 tools\make_data.py [示意网页路径]

默认读取 %USERPROFILE%\\Downloads\\星河读书会知识库助手_改版_v2.html。
写出 UTF-8（无 BOM）+ LF，与骨架 data/ 的正文逐字一致。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_HTML = Path(os.environ.get("USERPROFILE", "~")) / "Downloads" / "星河读书会知识库助手_改版_v2.html"

# 教师资料的期望字符数（LF 归一后），用于自校验
EXPECTED_CHARS = {
    "01_活动说明.md": 304,
    "02_借阅规则.md": 294,
    "03_空间预约.md": 307,
    "04_期刊与工具书.md": 369,
    "05_活动调整通知.md": 388,
    "06_成员留言摘录.md": 369,
}
# 已实测的 sha256 前 16 位，用于确认没有抽错
EXPECTED_SHA16 = {
    "01_活动说明.md": "39b9c3216aaf0945",
    "02_借阅规则.md": "3ee664fdb872402b",
    "03_空间预约.md": "462d306ada07b45c",
    "04_期刊与工具书.md": "ec106a88799da569",
    "05_活动调整通知.md": "4a0d840c5350cea4",
    "06_成员留言摘录.md": "2ab5f574fda18412",
}

DOC_RE = re.compile(
    r'\{name:"([^"]+)",\s*verified:(true|false),\s*text:"((?:[^"\\]|\\.)*)"\}',
    re.S,
)


def extract_docs(html: str) -> list[dict]:
    start = html.find("const DOCS")
    if start < 0:
        raise SystemExit("示意网页里没有找到 const DOCS")
    end = html.find("];", start)
    block = html[start:end]
    docs = []
    for name, verified, raw in DOC_RE.findall(block):
        text = json.loads('"' + raw + '"')          # 还原 \n 与引号转义
        docs.append({"name": name, "verified": verified == "true", "text": text})
    if len(docs) != 6:
        raise SystemExit(f"期望抽出 6 份资料，实际 {len(docs)} 份")
    return docs


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HTML
    if not src.is_file():
        raise SystemExit(f"找不到示意网页：{src}")
    html = src.read_text(encoding="utf-8")
    docs = extract_docs(html)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ok = True
    for doc in docs:
        name, text = doc["name"], doc["text"]
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        target = DATA_DIR / name
        target.write_text(normalized, encoding="utf-8", newline="\n")
        chars = len(normalized)
        sha16 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        flag_chars = "OK" if EXPECTED_CHARS.get(name) == chars else "字符数不符"
        flag_sha = "OK" if EXPECTED_SHA16.get(name) == sha16 else "sha不符"
        if flag_chars != "OK" or flag_sha != "OK":
            ok = False
        print(f"{name}\t{chars} 字\t{sha16}\t{flag_chars}/{flag_sha}\tverified={doc['verified']}")
    print("资料写入完成：", DATA_DIR)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
