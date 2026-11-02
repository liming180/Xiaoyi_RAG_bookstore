"""生成 test/fixtures/sample_big.md（>2MB，用于验证上传拒绝分支）。

不要手打大文件：本脚本用重复正文拼到 2.1MB。内容与 assets/data/02_借阅规则.md 同义，
只是重复拼接，避免引入新的业务事实。

用法::

    py -3.12 -X utf8 test/fixtures/_make_big.py
"""

from __future__ import annotations

from pathlib import Path

TARGET_BYTES = 2_100_000  # 2.1MB，略大于 2 * 1024 * 1024 = 2_097_152

PARAGRAPH = (
    "本段为测试用重复正文。已登记成员每人最多同时借阅4本普通图书，每本借期21天；"
    "工具书只能在书屋内阅览，不得外借。普通图书在到期前可申请续借1次，续借增加7天。"
    "已经逾期或被其他成员预约的图书不能续借。归还时将图书交至前台，由工作人员检查并完成登记。"
    "本文没有提供赔偿金额，聊天助手不得编造。\n\n"
)


def build() -> str:
    parts = ["# 星河读书会借阅规则（超大测试样本）\n\n"]
    size = len(parts[0].encode("utf-8"))
    index = 0
    while size < TARGET_BYTES:
        index += 1
        block = f"## 重复段落 {index}\n\n{PARAGRAPH}"
        parts.append(block)
        size += len(block.encode("utf-8"))
    return "".join(parts)


def main() -> None:
    out = Path(__file__).resolve().parent / "sample_big.md"
    text = build()
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"written {out} bytes={out.stat().st_size} chars={len(text)}")


if __name__ == "__main__":
    main()
