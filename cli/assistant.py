"""命令行版助手（与网页版共用同一套 app 模块）。

用法：
    py -3.12 -X utf8 cli/assistant.py

命令：
    /index            建库（显示进度与片段数）
    /search 完整问题   只检索，不调用模型
    /mode direct|rag|both
    /k 1..5
    /new              清空对话（历史不再携带）
    /show             查看当前会话与上一次发送的消息
    /quit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chat, chunking, prompting, retrieval, session, store       # noqa: E402
from app.embedding import embed_query                                      # noqa: E402
from app.settings import (                                                 # noqa: E402
    DATA_DIR, K_DEFAULT, K_MAX, K_MIN, AppError, is_mock, load_config, runtime_keys,
)

HELP = """可用命令：
  /index            建库并显示片段数
  /search 完整问题   只检索不回答
  /mode direct|rag|both  切换回答模式
  /k 1..5           调整取回片段数
  /new              清空对话
  /show             显示会话状态与上一次消息
  /help             显示本帮助
  /quit             退出"""


def show_status() -> None:
    cfg = load_config()
    snapshot = session.snapshot()
    state = store.status()
    print(f"  模式：{snapshot['mode']}    k = {snapshot['k']}    会话：{snapshot['session_id']}")
    print(f"  资料：{state['doc_count']} 份    片段：{state['chunks']}    分块：{state['chunk_size']}/{state['chunk_overlap']}")
    ready = "就绪" if state["ready"] else ("需要重新建库" if state["stale"] else "未建库")
    print(f"  知识库：{ready}")
    provider = "离线模拟" if is_mock(cfg) else f"真实接口（{cfg.get('model')}）"
    print(f"  通道：{provider}")


def do_index() -> None:
    def progress(done: int, total: int) -> None:
        percent = int(done / total * 100) if total else 0
        print(f"\r  正在向量化 {done}/{total}（{percent}%）", end="", flush=True)

    try:
        result = store.build_index(progress=progress)
    except AppError as exc:
        print(f"\n  建库失败：{exc}")
        return
    print()
    print(f"  建库成功，文档 {result['docs']} 份，片段 {result['chunks']} 条。")


def do_search(question: str) -> None:
    cfg = load_config()
    try:
        index = store.read_index()
    except AppError as exc:
        print(f"  {exc}")
        return
    trace = retrieval.rank_all(index["chunks"], embed_query(cfg, question))
    k = session.current_k()
    print(f"  共 {len(trace)} 个片段，按得分降序（前 {k} 条会送进提示词）：")
    for row in trace[:max(k + 3, 6)]:
        flag = "取回" if row["rank"] <= k else "    "
        mark = "" if row.get("verified", True) else " ⚠未核实"
        print(f"   {flag} #{row['rank']:<2} {row['chunk_id']}  {row['score']:.4f}  {row['source']}{mark}")
        print(f"        {row['text'][:70].replace(chr(10), ' ')}…")


def do_show() -> None:
    show_status()
    history = session.get_history()
    print(f"  历史消息：{len(history)} 条")
    record = store.last_log()
    if record:
        print("  上一次请求的消息结构：")
        for item in record.get("messages", []):
            body = item.get("content", "")
            preview = body if len(body) <= 200 else body[:200] + "…"
            print(f"   - {item.get('role')}: {preview}")
    else:
        print("  还没有请求记录。")


def do_ask(question: str) -> None:
    try:
        payload = chat.ask(question)
    except AppError as exc:
        print(f"  回答失败：{exc}")
        return

    if payload["mode"] == "both":
        print("\n  【查资料】")
        print(f"  {payload['rag']['answer']}")
        print("\n  【不查资料】")
        print(f"  {payload['direct']['answer']}")
        hits = payload["rag"]["citations"]
        trace = payload["rag"]["trace"]
    else:
        print(f"\n  {payload['answer']}")
        hits = payload["citations"]
        trace = payload["trace"]

    if hits:
        print("\n  本轮来源：")
        for card in hits:
            mark = "" if card["verified"] else "（未核实）"
            print(f"   [{card['ref']}] {card['chunk_id']}  {card['source']}{mark}  得分 {card['score']}")
    elif payload["mode"] != "direct":
        print("\n  本轮没有取回任何片段。")

    if trace:
        print("\n  检索过程（全部片段按得分降序，k 为截取线）：")
        for row in trace:
            flag = "→" if row["retrieved"] else " "
            print(f"   {flag} #{row['rank']:<2} {row['chunk_id']}  {row['score']:.4f}  {row['source']}")
    print()


def main() -> None:
    cfg = load_config()
    print("星河读书会 · 个人资料助手（命令行版）")
    show_status()
    if is_mock(cfg):
        print("  提示：当前是离线模拟档，回答由本地规则生成；接入教师接口请改 config.json 的 provider。")
    chat_key, _ = runtime_keys()
    if not is_mock(cfg) and not chat_key:
        print("  提示：未检测到密钥，可先设置环境变量 RAG_CHAT_KEY，或用网页版在内存里填入。")
    print("  输入 /help 查看命令。\n")

    while True:
        try:
            line = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return
        if not line:
            continue
        if line in {"/quit", "/exit", "/q"}:
            print("再见。")
            return
        if line == "/help":
            print(HELP)
            continue
        if line == "/index":
            do_index()
            continue
        if line == "/new":
            data = session.new_session()
            print(f"  已清空对话，新会话 {data['session_id']}（模式与 k 保持不变）。")
            continue
        if line == "/show":
            do_show()
            continue
        if line.startswith("/search"):
            question = line[len("/search"):].strip()
            if not question:
                print("  用法：/search 完整问题")
                continue
            do_search(question)
            continue
        if line.startswith("/mode"):
            value = line[len("/mode"):].strip()
            try:
                data = session.set_params(value or None, None)
            except AppError as exc:
                print(f"  {exc}")
                continue
            print(f"  当前模式：{data['mode']}（切换模式会清空对话）")
            continue
        if line.startswith("/k"):
            value = line[len("/k"):].strip()
            try:
                data = session.set_params(None, int(value) if value else None)
            except ValueError:
                print(f"  用法：/k {K_MIN}..{K_MAX}")
                continue
            except AppError as exc:
                print(f"  {exc}")
                continue
            print(f"  当前 k = {data['k']}")
            continue
        if line.startswith("/"):
            print("  未知命令，输入 /help 查看。")
            continue
        do_ask(line)


if __name__ == "__main__":
    try:
        main()
    except AppError as exc:      # pragma: no cover
        print(f"启动失败：{exc}")
        sys.exit(1)
