"""一轮问答的编排：检索 → 拼消息 → 调模型 → 引用校验 → 写日志（对应 F4 / F5 / F6 / F7 / F8 / F11）。"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from . import llm, prompting, retrieval, session, store
from .embedding import embed_query
from .settings import AppError, is_mock, load_config, runtime_keys


def _retrieve(cfg: dict[str, Any], question: str, k: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """检索并切出前 k 条；返回 (hits, trace)。trace 保留全量排序（F8）。"""
    index = store.read_index()
    query_vector = embed_query(cfg, question)
    trace = retrieval.rank_all(index["chunks"], query_vector)
    hits, trace = retrieval.split_trace(trace, k)
    return hits, trace


def answer_once(question: str, mode: str, k: int, log: bool = True) -> dict[str, Any]:
    """执行一次问答；mode = rag / direct。both 由上层调用两次拼装。"""
    if not question or not question.strip():
        raise AppError("问题不能为空。")
    question = question.strip()
    if mode not in {"rag", "direct"}:
        raise AppError("单次问答模式只能是 rag 或 direct。")

    cfg = load_config()
    chat_key, _ = runtime_keys()
    started = time.perf_counter()
    hits: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    if mode == "rag":
        hits, trace = _retrieve(cfg, question, k)

    system_prompt = prompting.SYSTEM_PROMPT if mode == "rag" else prompting.DIRECT_PROMPT
    history = session.get_history()
    messages = prompting.build_rag_messages(system_prompt, history, question, hits)

    try:
        text, usage = llm.answer(cfg, chat_key, messages, question, hits)
        status = "ok"
    except AppError as exc:
        if log:
            store.append_log({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "session_id": session.snapshot()["session_id"],
                "mode": mode,
                "provider": cfg.get("provider"),
                "model": cfg.get("model", ""),
                "embedding_model": cfg.get("embedding_model", ""),
                "top_k": k,
                "chunk_size": cfg.get("chunk_size"),
                "chunk_overlap": cfg.get("chunk_overlap"),
                "question": question,
                "retrieved": retrieval.public_hits(hits),
                "messages": messages,
                "answer": "",
                "usage": None,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "status": f"error: {exc}",
            })
        raise AppError(str(exc)) from None

    cleaned, removed = prompting.strip_invalid_citations(text, hits)
    if removed and log:
        status = "ok (剔除无效编号: " + ",".join(dict.fromkeys(removed)) + ")"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    user_content = messages[-1]["content"]
    session.append_turn(question, cleaned, user_content)

    unverified_hit = any(not hit.get("verified", True) for hit in hits)
    if log:
        store.append_log({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": session.snapshot()["session_id"],
            "mode": mode,
            "provider": cfg.get("provider"),
            "model": cfg.get("model", ""),
            "embedding_model": cfg.get("embedding_model", ""),
            "top_k": k,
            "chunk_size": cfg.get("chunk_size"),
            "chunk_overlap": cfg.get("chunk_overlap"),
            "question": question,
            "retrieved": retrieval.public_hits(hits),
            "messages": messages,
            "answer": cleaned,
            "usage": usage,
            "elapsed_ms": elapsed_ms,
            "status": status,
        })

    return {
        "mode": mode,
        "answer": cleaned,
        "citations": prompting.citations_from_hits(hits),
        "trace": prompting.trace_rows(trace, k) if trace else [],
        "used_knowledge_base": bool(hits),
        "unverified_hit": unverified_hit,
        "removed_citations": list(dict.fromkeys(removed)),
        "elapsed_ms": elapsed_ms,
        "usage": usage,
    }


def chat(question: str, mode: str, k: int) -> dict[str, Any]:
    """对外入口，支持 rag / direct / both。both 用同一 question 各跑一次、互不影响历史。"""
    if mode not in {"rag", "direct", "both"}:
        raise AppError("模式只能是 rag、direct 或 both。")
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 5:
        raise AppError("k 须为 1 至 5 的整数。")

    snapshot = session.snapshot()
    payload: dict[str, Any] = {
        "mode": mode,
        "k": k,
        "session_id": snapshot["session_id"],
        "provider": load_config().get("provider"),
        "mock": is_mock(),
    }

    if mode == "both":
        # 两种模式各答一次：先记下 history，跑完 rag 后还原，避免 direct 受 rag 影响
        history_before = session.get_history()
        rag_result = answer_once(question, "rag", k, log=False)
        session.set_history(history_before)
        direct_result = answer_once(question, "direct", k, log=False)
        session.set_history(history_before)
        payload["rag"] = rag_result
        payload["direct"] = direct_result
        payload["answer"] = rag_result["answer"]
        payload["citations"] = rag_result["citations"]
        payload["trace"] = rag_result["trace"]
        payload["used_knowledge_base"] = rag_result["used_knowledge_base"]
        payload["unverified_hit"] = rag_result["unverified_hit"]
        payload["removed_citations"] = rag_result["removed_citations"]
        payload["elapsed_ms"] = rag_result["elapsed_ms"] + direct_result["elapsed_ms"]
        store.append_log({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": snapshot["session_id"],
            "mode": "both",
            "provider": payload["provider"],
            "question": question,
            "top_k": k,
            "answer": rag_result["answer"],
            "direct_answer": direct_result["answer"],
            "retrieved": [card["chunk_id"] for card in rag_result["citations"]],
            "status": "ok",
        })
        return payload

    result = answer_once(question, mode, k)
    payload.update(result)
    return payload


def ask(question: str, mode: str | None = None, k: int | None = None) -> dict[str, Any]:
    """命令行/批量测试共用的薄封装：不传 mode/k 时用会话当前值。"""
    use_mode = mode or session.current_mode()
    use_k = k if k is not None else session.current_k()
    if use_mode == "both":
        return chat(question, "both", use_k)
    return chat(question, use_mode, use_k)


def new_session() -> dict[str, Any]:
    return session.new_session()


def set_params(mode: str | None, k: int | None) -> dict[str, Any]:
    return session.set_params(mode, k)
