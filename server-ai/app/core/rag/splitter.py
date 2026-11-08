"""递归切片：按 Markdown 标题继承章节路径，再按段落 / 句子 / 硬切逐级回退。

设计约束（来自 `docs/02-重构设计/04_后端开发提示词.md` A2 段与
`docs/api/openapi-internal.yaml` 的 InternalCitation）：

* 每个切片必须带可读的 `heading_path`，不能是固定占位串；
* `start` / `end` 是原文偏移，必须满足 `start < end`、整体单调不减、覆盖无空洞；
* `chunk_id` 满足契约 pattern `^D\\d{2}-C\\d{3}$`；
* 切片之间保留 `overlap` 个字符的重叠，`overlap` 不得把窗口推成零步长。

本模块是纯函数，不依赖网络与数据库，便于单测直接构造语料断言。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# 契约要求 chunk_id 形如 D01-C001，单文档切片数上限 999；
# 文档编号是两位（D01..D99），所以单用户文档数上限 99。
MAX_CHUNKS_PER_DOC = 999
MAX_DOCS_PER_USER = 99

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
# 句子边界：中文句号/问叹号/分号，或英文句点后跟空白。用于二级回退。
_SENTENCE = re.compile(r"[。！？；!?;]|\.(?=\s)")

# 命中即视为「疑似指令注入」的片段，只降低可信标记，不改切片内容。
_POISON = re.compile(
    r"(忽略(你)?(之前|以上|前面)(收到)?的?(所有)?(规则|指令|提示)"
    r"|你现在是\s*DAN"
    r"|system\s*prompt"
    r"|系统提示词"
    r"|管理员(的)?联系电话)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Section:
    """一个 Markdown 章节在原文中的范围。"""

    heading_path: str
    start: int
    end: int


@dataclass(frozen=True)
class Piece:
    """一个切片的原文范围与所属章节。"""

    heading_path: str
    start: int
    end: int


def iter_sections(text: str, fallback_title: str = "") -> list[Section]:
    """按 Markdown 标题把正文切成章节，标题路径逐级继承。

    没有标题的文档整篇算一个章节，`heading_path` 回落到文档标题。
    """
    if not text:
        return [Section(heading_path=fallback_title or "", start=0, end=0)]

    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)

    marks: list[tuple[int, int, str]] = []  # (offset, level, title)
    for index, line in enumerate(lines):
        matched = _HEADING.match(line.rstrip("\r\n"))
        if matched:
            marks.append((offsets[index], len(matched.group(1)), matched.group(2).strip()))

    if not marks:
        return [Section(heading_path=fallback_title or "", start=0, end=len(text))]

    sections: list[Section] = []
    # 第一个标题之前的内容也保留，用文档标题兜底。
    if marks[0][0] > 0:
        sections.append(
            Section(heading_path=fallback_title or "", start=0, end=marks[0][0])
        )

    stack: list[tuple[int, str]] = []
    for position, (offset, level, title) in enumerate(marks):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = " > ".join(f"{'#' * lv} {name}" for lv, name in stack)
        end = marks[position + 1][0] if position + 1 < len(marks) else len(text)
        if end > offset:
            sections.append(Section(heading_path=path, start=offset, end=end))
    return sections


def _trim_to_boundary(text: str, start: int, hard_end: int, floor: int) -> int:
    """把窗口右端回退到段落或句子边界，回退幅度不超过窗口的 40%。

    `floor` 是允许的最小右端，避免长句被切成过短的碎片。
    """
    if hard_end >= len(text):
        return hard_end
    span = hard_end - start
    limit = max(floor, hard_end - int(span * 0.4))
    window = text[limit:hard_end]

    para = window.rfind("\n\n")
    if para >= 0:
        return limit + para + 2

    sentence = None
    for matched in _SENTENCE.finditer(window):
        sentence = matched.end()
    if sentence is not None:
        return limit + sentence

    space = window.rfind("\n")
    if space >= 0:
        return limit + space + 1

    return hard_end


def split_section(
    text: str,
    section: Section,
    chunk_size: int,
    overlap: int,
) -> list[Piece]:
    """把一个章节切成若干窗口，窗口之间保留 `overlap` 字符重叠。"""
    chunk_size = max(1, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 1))
    step_floor = max(1, chunk_size - overlap)

    pieces: list[Piece] = []
    cursor = section.start
    while cursor < section.end and len(pieces) < MAX_CHUNKS_PER_DOC:
        hard_end = min(section.end, cursor + chunk_size)
        end = _trim_to_boundary(text, cursor, hard_end, cursor + step_floor)
        if end <= cursor:
            end = hard_end
        pieces.append(Piece(heading_path=section.heading_path, start=cursor, end=end))
        if end >= section.end:
            break
        # 下一窗口从「本窗口右端 - overlap」开始，但至少前进 step_floor，
        # 否则边界回退过多时会退化成零步长死循环。
        cursor = max(cursor + step_floor, end - overlap)
    return pieces


def split_text(
    text: str,
    chunk_size: int,
    overlap: int,
    fallback_title: str = "",
) -> list[Piece]:
    """整篇切分：逐章节切，跨章节累计不超过 MAX_CHUNKS_PER_DOC。"""
    pieces: list[Piece] = []
    for section in iter_sections(text, fallback_title):
        if len(pieces) >= MAX_CHUNKS_PER_DOC:
            break
        if section.end <= section.start:
            continue
        room = MAX_CHUNKS_PER_DOC - len(pieces)
        pieces.extend(split_section(text, section, chunk_size, overlap)[:room])
    if not pieces:
        pieces.append(Piece(heading_path=fallback_title or "", start=0, end=len(text)))
    return pieces


def chunk_id(doc_no: int, index: int) -> str:
    """契约要求的切片编号：D + 两位文档号 + -C + 三位序号。"""
    return f"D{doc_no:02d}-C{index:03d}"


def is_suspicious(excerpt: str) -> bool:
    """疑似指令注入的片段标记为不可信（verified=False），内容照原样保留。"""
    return bool(_POISON.search(excerpt or ""))


def build_pieces(
    text: str,
    doc_no: int,
    chunk_size: int,
    overlap: int,
    fallback_title: str = "",
) -> Iterable[dict[str, Any]]:
    """产出与 Citation 契约字段对齐的切片字典序列。"""
    for index, piece in enumerate(split_text(text, chunk_size, overlap, fallback_title), start=1):
        excerpt = text[piece.start : piece.end]
        yield {
            "chunk_id": chunk_id(doc_no, index),
            "heading_path": piece.heading_path,
            "excerpt": excerpt,
            "start": piece.start,
            "end": piece.end,
            "kind": "chunk",
            "verified": not is_suspicious(excerpt),
        }
