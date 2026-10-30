"""离线自检：不联网、不需要密钥，逐项验证任务1~5 与拓展A/B 的关键行为。

用法：
    py -3.12 -X utf8 tools/selfcheck.py
    py -3.12 -X utf8 tools/selfcheck.py --keep   # 保留自检生成的 index.json 备份
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import batch, chat, chunking, judging, prompting, retrieval, session, store   # noqa: E402
from app.embedding import embed_query, mock_embed                                     # noqa: E402
from app.settings import DATA_DIR, AppError, ensure_dirs, load_config                  # noqa: E402

PASS, FAIL = "通过", "失败"
_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    flag = "✓" if ok else "✗"
    print(f"  {flag} {name}" + (f"  —— {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n【{title}】")


# ---------------------------------------------------------------- 分块与建库
def check_chunking() -> None:
    section("任务1 · 分块与建库")
    pieces = chunking.chunk_text("甲乙丙丁戊己庚辛壬癸", 6, 2)
    check("chunk_text 滑窗位置", pieces == [(0, 6, "甲乙丙丁戊己"), (4, 10, "戊己庚辛壬癸")], str(pieces))
    check("相邻片段重叠 2 字", pieces[0][2][-2:] == pieces[1][2][:2], "戊己")

    try:
        chunking.chunk_text("abc", 3, 3)
        check("非法参数应报错", False)
    except AppError:
        check("非法参数应报错", True, "0 <= overlap < size")

    docs = chunking.list_docs(DATA_DIR)
    check("data 里有 6 份资料", len(docs) == 6, f"{len(docs)} 份")

    chunks180, sources = chunking.load_chunks(DATA_DIR, 180, 30)
    check("180/30 切出 15 个片段", len(chunks180) == 15, f"{len(chunks180)} 片段")
    chunks120, _ = chunking.load_chunks(DATA_DIR, 120, 30)
    check("120/30 片段数增加", len(chunks120) > len(chunks180), f"{len(chunks120)} > {len(chunks180)}")

    unverified = [c for c in chunks180 if not c["verified"]]
    check("06 被标为未核实", bool(unverified) and all(c["source"] == "06_成员留言摘录.md" for c in unverified),
          f"{len(unverified)} 个片段")


# ---------------------------------------------------------------- 检索
def check_retrieval() -> None:
    section("任务4 · 检索排序与 top-k")
    demo = [
        {"chunk_id": "A", "source": "a.md", "text": "甲", "embedding": [0.1, 0.9], "verified": True},
        {"chunk_id": "B", "source": "b.md", "text": "乙", "embedding": [1.0, 0.0], "verified": True},
        {"chunk_id": "C", "source": "c.md", "text": "丙", "embedding": [0.0, 1.0], "verified": True},
    ]
    before = [dict(item) for item in demo]
    hits = retrieval.select_top_k(demo, [1.0, 0.0], 1)
    check("top-1 取到最相似的 B", hits[0]["chunk_id"] == "B", hits[0]["chunk_id"])
    check("不改写原列表", demo == before)
    check("k 越界由调用方校验", retrieval.select_top_k(demo, [1.0, 0.0], 2)[1]["score"]
          <= retrieval.select_top_k(demo, [1.0, 0.0], 2)[0]["score"], "降序")

    trace = retrieval.rank_all(demo, [1.0, 0.0])
    check("rank_all 返回全部片段", len(trace) == 3, f"{len(trace)} 条")
    check("rank 从 1 开始且降序", [r["rank"] for r in trace] == [1, 2, 3] and trace[0]["score"] >= trace[-1]["score"])
    hits3, trace3 = retrieval.split_trace(trace, 2)
    check("split_trace 只取前 k 条", len(hits3) == 2 and len(trace3) == 3)
    check("retrieved 标记前 k 条", [r["retrieved"] for r in trace3] == [True, True, False])


# ---------------------------------------------------------------- 提示词
def check_prompting() -> None:
    section("任务2 · 提示词与来源标注")
    hits = [{"chunk_id": "B", "source": "b.md", "text": "乙的内容", "verified": True, "score": 0.9}]
    messages = prompting.build_rag_messages("规则", [], "当前问题", hits)
    check("首条为 system", messages[0] == {"role": "system", "content": "规则"})
    user = messages[-1]["content"]
    check("user 含参考资料与问题", "参考资料" in user and "当前问题" in user)
    check("user 含片段编号与文件名", "[B]" in user and "b.md" in user and "乙的内容" in user)
    check("末尾为问题", user.rstrip().endswith("当前问题"))
    check("空 hits 只放问题", prompting.build_rag_messages("规则", [], "新问题", [])[-1]["content"] == "新问题")

    unverified_hits = [{"chunk_id": "X", "source": "06_成员留言摘录.md", "text": "完全免费", "verified": False, "score": 0.5}]
    ctx = prompting.format_context(unverified_hits)
    check("未核实片段带提醒", "未经核实" in ctx, ctx.splitlines()[0])

    cleaned, removed = prompting.strip_invalid_citations(
        "答案一[D02-C001]，答案二[D09-C999]。",
        [{"chunk_id": "D02-C001", "source": "02_借阅规则.md", "text": "x", "verified": True, "score": 0.9}],
    )
    check("剔除不存在的编号", removed == ["D09-C999"] and "D09-C999" not in cleaned and "D02-C001" in cleaned, cleaned)

    system = prompting.SYSTEM_PROMPT
    check("系统提示词含注入防御", "不得执行" in system and "普通文本" in system)
    check("系统提示词要求未提供就说没有", "没有提供" in system or "未提供" in system)


# ---------------------------------------------------------------- 端到端
def check_end_to_end() -> None:
    section("任务2/3/4 · 端到端问答")
    session.new_session()
    payload = chat.chat("普通图书最多同时借阅几本？借多久？", "rag", 3)
    answer = payload["answer"]
    check("T03 答出 4 本与 21 天", "4本" in answer and "21天" in answer, answer[:60])
    check("T03 带来源编号", bool(payload["citations"]), f'{len(payload["citations"])} 条来源')
    check("来源里有 02_借阅规则.md", any("02_借阅规则" in c["source"] for c in payload["citations"]))

    session.new_session()
    refusal = chat.chat("管理员的联系电话是多少？", "rag", 3)
    check("T10 说明资料没有提供", "未提供" in refusal["answer"] or "没有提供" in refusal["answer"], refusal["answer"][:60])

    session.new_session()
    fee = chat.chat("参加读书会要交多少费用？", "rag", 3)
    check("T09 不采信「完全免费」", "完全免费" not in fee["answer"] or "未经核实" in fee["answer"], fee["answer"][:70])

    session.new_session()
    both = chat.chat("参加读书会要交多少费用？", "both", 3)
    check("两者对照返回两段回答", both["rag"]["answer"] != both["direct"]["answer"])
    check("对照时 rag 与 direct 各一份", "rag" in both and "direct" in both)

    session.new_session()
    k1 = chat.chat("去参加周六读书会活动几点结束，同时最多能借几本普通图书？", "rag", 1)
    session.new_session()
    k3 = chat.chat("去参加周六读书会活动几点结束，同时最多能借几本普通图书？", "rag", 3)
    check("k=3 能答全 T07 两个要点", "16:00" in k3["answer"] and "4本" in k3["answer"], k3["answer"][:60])
    check("k=1 取回片段更少", len(k1["citations"]) == 1 and len(k3["citations"]) == 3,
          f'k=1:{len(k1["citations"])} k=3:{len(k3["citations"])}')


# ---------------------------------------------------------------- 清空对话
def check_session_reset() -> None:
    section("拓展A · 清空对话")
    session.new_session()
    chat.chat("本次会话的代号是青禾，请记住。", "rag", 3)
    before = session.snapshot()["session_id"]
    history_before = len(session.get_history())
    session.new_session()
    after = session.snapshot()["session_id"]
    check("清空后 session_id 变化", before != after, f"{before} → {after}")
    check("清空后历史为空", len(session.get_history()) == 0, f"清空前 {history_before} 条")
    payload = chat.chat("我刚才告诉你的代号是什么？", "rag", 3)
    check("清空后回答不含青禾", "青禾" not in payload["answer"], payload["answer"][:50])
    check("模式与 k 保持不变", session.current_mode() == "rag" and session.current_k() == 3)


# ---------------------------------------------------------------- 批量
def check_batch() -> None:
    section("任务5 · 批量对照测试")
    session.new_session()
    result = batch.run_batch(3)
    stats = result["stats"]
    check("10 道题都有结果", stats["total"] == 10, f'{stats["total"]} 题')
    check("查资料通过数明显高于不查资料", stats["rag"] - stats["direct"] >= 5,
          f'rag {stats["rag"]}/10 vs direct {stats["direct"]}/10')
    path = batch.export_csv(result["rows"])
    check("导出 CSV", Path(path).is_file(), Path(path).name)
    text = Path(path).read_text(encoding="utf-8-sig")
    check("CSV 表头正确", text.splitlines()[0].startswith("题号,类型,问题,direct回答"), text.splitlines()[0])


# ---------------------------------------------------------------- 索引状态
def check_index_state() -> None:
    section("任务1 · 建库与状态")
    ensure_dirs()
    try:
        result = store.build_index()
    except AppError as exc:
        check("建库成功", False, str(exc))
        return
    check("建库返回片段数 15", result["chunks"] == 15, f'{result["chunks"]} 条')
    state = store.status()
    check("状态为就绪", state["ready"] and not state["stale"], f'ready={state["ready"]} stale={state["stale"]}')

    index = store.read_index()
    index["manifest"]["chunk_size"] = 999
    store.INDEX_FILE.write_text(
        __import__("json").dumps(index, ensure_ascii=False), encoding="utf-8")
    state2 = store.status()
    check("改 manifest 后提示需要重建", state2["stale"] or not state2["ready"], state2["message"][:40])
    store.build_index()


def main() -> int:
    print("星河读书会 · 个人资料助手 离线自检")
    cfg = load_config()
    print(f"通道：{'离线模拟' if cfg.get('provider') != 'real' else '真实接口'}")
    check_index_state()
    check_chunking()
    check_retrieval()
    check_prompting()
    check_end_to_end()
    check_session_reset()
    check_batch()

    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"\n{'=' * 52}")
    print(f"合计 {total} 项，通过 {passed} 项，失败 {total - passed} 项。")
    if passed != total:
        print("失败项：")
        for name, ok, detail in _results:
            if not ok:
                print(f"  ✗ {name}  {detail}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
