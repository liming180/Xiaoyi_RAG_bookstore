"""切片与任务推进：解析、切片、向量化、摘要四段进度，以及按用户范围检索。

A2 起，切分与检索不再用固定滑窗 + 关键词打分，而是：
1. `core.rag.splitter` 递归切分（Markdown 标题继承 + 段落/句子边界回退）；
2. `core.rag.embedder` 向量化（mock 档确定性哈希向量，real 档打 OpenAI 兼容服务）；
3. `core.vector_store.store` 落库并按 `user_id` / `task_id` 过滤检索。

SQLite（`state`）仍是切片元数据的权威来源：Java 建库轮询拿到 `data.chunks`
才会把片段缓存进 MySQL 的 chunk 表。向量只进向量库，不进 MySQL，也不进 SQLite。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import get_settings
from ..core.rag import pipeline, prompt, summarizer
from ..core.rag.embedder import Embedder, embedder_from_settings
from ..core.rag.fusion import reciprocal_rank_fusion
from ..core.rag.reranker import QueryRewriter, Reranker, reranker_from_settings
from ..core.rag.retriever import bm25_cache
from ..core.rag.splitter import MAX_CHUNKS_PER_DOC, MAX_DOCS_PER_USER, build_pieces
from ..core.vector_store.store import VectorStore, store_from_settings
from ..schemas.models import ParseDocument, ParseRequest, RetrieveRequest
from . import state

# 索引清单在无成功任务时回退到的默认切片参数。必须与 Java 侧
# `xiaoyi.index.default-chunk-size` / `default-overlap` 保持一致（180 / 30），
# 否则 `/index/status` 会因 manifest 与最近成功任务参数不符而恒为 needs_rebuild。
DEFAULT_CHUNK_SIZE = 180
DEFAULT_OVERLAP = 30

#: 引用里允许出现的 score_stage 取值（契约 enum）。
SCORE_STAGES = ("dense", "sparse", "rrf", "rerank")

logger = logging.getLogger(__name__)


class _Runtime:
    """进程内单例：向量库与 embedder 都要跨请求复用（建集合、缓存维度）。"""

    def __init__(self) -> None:
        self._store: VectorStore | None = None
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None
        self._rewriter: QueryRewriter | None = None
        self._provider: Any = None
        self._dim = 0

    def store(self) -> VectorStore:
        if self._store is None:
            self._store = store_from_settings(get_settings())
        return self._store

    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = embedder_from_settings(get_settings())
        return self._embedder

    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = reranker_from_settings(get_settings())
        return self._reranker

    def rewriter(self) -> QueryRewriter:
        if self._rewriter is None:
            self._rewriter = QueryRewriter(get_settings())
        return self._rewriter

    def provider(self):
        """建库阶段用的 LLM provider（摘要卡生成）。

        与 chat 链路用的是同一套 `provider_from_settings`，但**单独缓存**：建库在
        后台线程里跑，每次重建都新起一个 provider 会把连接池反复丢弃。
        """
        if self._provider is None:
            from ..core.llm.provider import provider_from_settings

            self._provider = provider_from_settings(get_settings())
        return self._provider

    def reset(self) -> None:
        """测试切换 settings 时清空缓存。"""
        self._store = None
        self._embedder = None
        self._reranker = None
        self._rewriter = None
        self._provider = None
        self._dim = 0
        bm25_cache.clear()

    def ensure_dim(self, dim: int) -> int:
        """按需建集合；维度以 embedder 首次返回为准。"""
        if dim > 0 and dim != self._dim:
            self.store().ensure(dim)
            self._dim = dim
        return self._dim


runtime = _Runtime()


def _pause() -> None:
    """阶段间停顿：让 Java 的轮询看得见完整阶段序列。

    `ingest_stage_delay_ms` 默认 0（全速）；门禁环境把它调到大于 Java 轮询间隔，
    否则五个阶段会在毫秒内跑完，轮询只能抓到 parsing 与 done。只影响观测粒度，不改结果。
    """
    delay_ms = get_settings().ingest_stage_delay_ms
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def _document_no(user_id: int, doc_id: str, title: str = "") -> int:
    """取文档在该用户下的稳定编号，用于拼 D01-C001 这类 chunk_id。

    编号是两位十进制（契约 `^D\\d{2}-C\\d{3}$`），所以一个用户**同时**最多 99 份资料。
    超出时由 `state.upsert_document` 抛出带动作的错，这里不再自己 clamp ——
    旧实现把 >99 压成 99，第 100 份起全部变成 `D99-Cxxx`，同一次 upsert 主键重复，
    Milvus 只回一句 `duplicate primary keys are not allowed in the same batch`。

    编号查不到时**就地补登记**而不是报错：并发建库时另一个任务可能刚回收过编号，
    这里补一次比让整个任务失败划算（实测踩过「资料 495 尚未登记编号」）。
    """
    doc_no = state.document_number(user_id, doc_id)
    if doc_no <= 0:
        doc_no = state.upsert_document(user_id, doc_id, title or doc_id, "PARSING", 0)
    if doc_no > MAX_DOCS_PER_USER:
        raise ValueError(
            f"资料数已达上限：用户 {user_id} 的第 {doc_no} 份资料无法编号"
            f"（chunk_id 的文档号只有两位，最多 {MAX_DOCS_PER_USER} 份）；"
            "请先删除不再需要的资料再建库"
        )
    return doc_no


def build_chunks(
    user_id: int,
    doc: ParseDocument,
    doc_no: int,
    req: ParseRequest,
) -> list[dict[str, Any]]:
    """把一份文档切成切片记录，字段与 Citation 契约一致。"""
    text = doc.text or doc.title or doc.name or ""
    title = doc.title or doc.name or doc.doc_id
    rows: list[dict[str, Any]] = []
    for piece in build_pieces(text, doc_no, req.chunk_size, req.overlap, title):
        rows.append(
            {
                "chunk_id": piece["chunk_id"],
                "doc_id": doc.doc_id,
                "doc_title": title,
                "heading_path": piece["heading_path"],
                "excerpt": piece["excerpt"],
                "start": piece["start"],
                "end": piece["end"],
                # 检索阶段会按向量相似度重算，这里只给一个占位值。
                "score": 0.0,
                "score_stage": "dense",
                "kind": piece["kind"],
                "verified": piece["verified"],
            }
        )
        if len(rows) >= MAX_CHUNKS_PER_DOC:
            break
    return rows


def _embed_and_store(
    user_id: int,
    task_id: str,
    rows: list[dict[str, Any]],
    *,
    keep_existing: bool = False,
) -> int:
    """把切片向量化并写入向量库；返回写入条数。

    @param user_id 归属用户
    @param task_id 建库任务号
    @param rows 切片行（已带 chunk_id / excerpt 等字段）
    @param keep_existing True 时不清空本任务已有切片 —— 摘要卡是**追加**写入：
        普通片段刚写进同一个 task 分区，清一次会把整库抹掉，建库直接变成只有两张卡
    @return 写入条数
    """
    if not rows:
        return 0
    embedder = runtime.embedder()
    store = runtime.store()
    vectors = embedder.embed([row["excerpt"] for row in rows])
    if len(vectors) != len(rows):
        raise RuntimeError(f"向量条数与切片不符：切片 {len(rows)}，向量 {len(vectors)}")
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    if dim <= 0:
        raise RuntimeError("向量化返回空向量")
    runtime.ensure_dim(dim)
    payload = [{**row, "vector": vector} for row, vector in zip(rows, vectors)]
    # 同一批里出现重复 chunk_id 时，Milvus 只回一句 code=1100 的 duplicate primary keys，
    # 看不出是哪份资料撞的。这里先自查并把「先出现的」和「撞上的」两方都点名，
    # 把定位成本从「翻库」降到「读报错」。
    owner: dict[str, str] = {}
    duplicated: list[str] = []
    for row in payload:
        chunk = row["chunk_id"]
        previous = owner.get(chunk)
        if previous is not None:
            duplicated.append(f"{chunk}: doc {previous} 与 doc {row['doc_id']}")
        else:
            owner[chunk] = str(row["doc_id"])
    if duplicated:
        raise ValueError("同一批切片出现重复 chunk_id：" + "；".join(sorted(set(duplicated))[:5]))
    if not keep_existing:
        # 先删同任务旧行，保证重放同一 submission_key 不会残留旧切片。
        store.delete_task(user_id, task_id)
    return store.upsert(user_id, task_id, payload)


def run_ingest(user_id: int, task_id: str, req: ParseRequest) -> None:
    """后台推进一次解析任务；任何异常都把任务置为 FAILED。"""
    try:
        # 先回收已删除资料占用的编号，再登记本次资料 —— 顺序反了的话，「已达上限」
        # 会在回收腾出空位之前就把任务判死（实测踩过）。
        released = state.reconcile_documents(
            user_id, [doc.doc_id for doc in req.documents], before=int(time.time())
        )
        if released:
            logger.info("用户 %s 建库前回收了 %s 份已删除资料", user_id, released)

        state.update_task(user_id, task_id, status="RUNNING", stage="parsing", progress=20)
        for doc in req.documents:
            state.upsert_document(user_id, doc.doc_id, doc.title or doc.name or doc.doc_id, "PARSING", 0)
        _pause()

        state.update_task(user_id, task_id, stage="splitting", progress=45)
        planned: list[tuple[ParseDocument, list[dict[str, Any]]]] = []
        for doc in req.documents:
            doc_no = _document_no(user_id, doc.doc_id, doc.title or doc.name or "")
            parts = build_chunks(user_id, doc, doc_no, req)
            planned.append((doc, parts))
        _pause()

        state.update_task(user_id, task_id, stage="embedding", progress=70)
        # 同一任务的所有文档合成一批写入，保证一次任务只有一个 task_id 分区。
        flat = [row for _doc, parts in planned for row in parts]
        stored = _embed_and_store(user_id, task_id, flat)
        for doc, parts in planned:
            state.replace_chunks(user_id, task_id, doc.doc_id, parts)
            state.upsert_document(
                user_id,
                doc.doc_id,
                doc.title or doc.name or doc.doc_id,
                "INDEXED",
                len(parts),
            )
        _pause()

        state.update_task(user_id, task_id, stage="summarizing", progress=90, chunk_count=stored)
        # N3：summarizing 阶段从「空转」变成真生成。失败**不改变任务终态** ——
        # 摘要卡是增强，不是建库的前提；降级为「无摘要卡」，任务照常 SUCCEEDED。
        cards = _summarize(user_id, task_id, req)
        stored += len(cards)
        if cards:
            state.replace_chunks(user_id, task_id, summarizer.SUMMARY_DOC_ID, cards)
        _pause()
        state.update_task(
            user_id,
            task_id,
            status="SUCCEEDED",
            stage="done",
            progress=100,
            chunk_count=stored,
            finished_at=int(time.time()),
        )
    except Exception as exc:  # 解析失败必须落库，避免任务永远停在 RUNNING
        state.update_task(
            user_id,
            task_id,
            status="FAILED",
            stage="done",
            progress=100,
            error=f"解析任务失败：{exc}",
            finished_at=int(time.time()),
        )


def _summarize(user_id: int, task_id: str, req: ParseRequest) -> list[dict[str, Any]]:
    """生成并写入摘要卡；返回写入的卡片行（失败返回空列表）。

    <p>为什么单独抽出来：它是唯一一条「失败也算成功」的路径，混在主流程里很难看出
    到底哪一步在容错。抽出来之后，`run_ingest` 里那一行读起来就是「这里不抛异常」。

    @param user_id 归属用户
    @param task_id 本次建库任务（摘要卡与普通片段同分区）
    @param req 解析请求（取语料与 gen_summary 开关）
    @return 写入的卡片行；未生成/生成失败时为空列表
    """
    if not req.gen_summary:
        # 开关关掉时**连 LLM 都不调**：门禁要能断言「关掉后一个摘要卡都没有」，
        # 而「调了但丢弃」会让这条断言依赖运气。
        logger.info("用户 %s 的建库任务跳过了摘要卡生成（gen_summary=false）", user_id)
        return []
    try:
        cards = summarizer.generate(runtime.provider(), req.documents)
    except Exception as exc:  # noqa: BLE001 - 摘要失败绝不能让建库失败
        logger.warning("摘要卡生成失败，本次建库降级为无摘要卡：%s", exc)
        return []
    if not cards:
        logger.info("用户 %s 的建库任务没有产出摘要卡（语料为空或模型输出不合格）", user_id)
        return []
    rows = summarizer.to_chunk_rows(user_id, task_id, cards)
    written = _embed_and_store(user_id, task_id, rows, keep_existing=True)
    if written != len(rows):
        logger.warning("摘要卡写入条数不符：期望 %s 实际 %s", len(rows), written)
    return rows



def _latest_task(user_id: int) -> str | None:
    latest = state.latest_succeeded_task(user_id)
    return str(latest["task_id"]) if latest else None


def _fallback_rows(user_id: int, req: RetrieveRequest) -> list[dict[str, Any]]:
    """向量库没数据时退回 SQLite 的切片（重启后内存实现为空，靠这条兜底）。"""
    task_id = _latest_task(user_id)
    if task_id is None:
        return []
    rows = state.list_chunks(user_id, task_id)
    allowed = set(req.doc_ids) if req.doc_ids else None
    found = [
        row
        for row in rows
        if (allowed is None or row["doc_id"] in allowed) and (not req.kind or row["kind"] == req.kind)
    ]
    for row in found:
        row["score"] = 0.5
        row["score_stage"] = "dense"
    return found[: req.k]


def _scoped_rows(user_id: int, task_id: str, req: RetrieveRequest) -> list[dict[str, Any]]:
    """BM25 的语料范围与向量路完全一致；先限定用户，再建倒排。

    @param user_id 归属用户
    @param task_id 建库任务号
    @param req 检索请求
    @return 倒排可用的切片行
    """
    rows = state.list_chunks(user_id, task_id)
    allowed = set(req.doc_ids) if req.doc_ids else None
    effective_kind = req.kind or "chunk"
    return [
        row for row in rows
        if (allowed is None or row["doc_id"] in allowed) and row["kind"] == effective_kind
    ]


def _best_card(
    user_id: int, task_id: str, vector: list[float], req: RetrieveRequest,
) -> dict[str, Any] | None:
    """取一张最优摘要卡，供 top-k 兜底使用（N3）。

    为什么摘要卡不参与自由竞争
    --------------------------
    摘要卡是「全库概览」，向量与任何具体问题都不算特别近，但也不算远 —— 让它在同一个
    top-k 里自由竞争，结果是它**随机地**挤掉真实片段（实测 3 条引用里有 2 条是卡片，
    用户问「借几本」，拿到的却是「全库共 6 份资料」）。所以正常召回只看 `kind=chunk`，
    摘要卡只在兜底路径上补末位。

    @param user_id 归属用户
    @param task_id 任务号
    @param vector 查询向量
    @param req 检索请求
    @return 最优摘要卡，没有则 None
    """
    if req.doc_ids or req.kind:
        # 用户显式限定了资料范围或类型时不做兜底：那不是「问全局」，补一张库里所有资料的
        # 概览卡会答非所问。
        return None
    store = runtime.store()
    # 统计卡优先于规则卡：问「一共多少」比问「谁有资格」更常见，且规则卡正文更长、
    # 塞进 3 条引用的上下文里更挤。
    for kind in ("summary", "rule"):
        hits = store.search(
            user_id=user_id, task_id=task_id, vector=vector, k=1, kind=kind,
        )
        if hits:
            return hits[0]
    return None


#: 「这句话在问整个资料库」的判据。必须与全局问答的实际说法对得上，宁可少判不可误判 ——
#: 误判的代价是每一条普通问答都被塞一张「全库共 N 份资料」的卡片。
_GLOBAL_MARKERS = (
    "一共",
    "总共",
    "多少份",
    "多少条",
    "全部",
    "整个",
    "所有",
    "资料库",
    "知识库",
    "汇总",
    "概览",
    "总览",
    "有哪些资料",
)


def _wants_global(question: str) -> bool:
    """判断问题是不是在问「整个资料库」。

    为什么要有这道闸（而不是「前 k 没卡片就补一张」）
    ------------------------------------------------
    提示词 §5.3 三的字面写法是「前 k 里没有任何 summary/rule 就替换末位」。按字面实现
    的结果是**每一个问题**都会被塞一张概览卡 —— k=3 时三分之一是「全库共 6 份资料」，
    而用户问的是「普通图书借几本」。实测 A3 的 `test_rrf_mode_shape` /
    `test_hybrid_mode_shape` / `test_options_rerank` 五条同时失败，失败原因正是
    「引用里混进了非精排档位的卡片」。

    所以改成：先判断问题是不是**真的**在问全局，再决定要不要补卡。判据是显式词表 ——
    可解释、可测试、不误伤普通问答。代价是改写过的口语（「这套资料都讲了些啥」）
    可能漏判，那种情况退回普通片段，不会答错，只是少一张卡。

    @param question 已改写的问题
    @return 是则 True
    """
    text = (question or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _GLOBAL_MARKERS)


def retrieve(
    user_id: int,
    req: RetrieveRequest,
    *,
    history: list[dict[str, str]] | None = None,
    mode: str | None = None,
    rerank: bool | None = None,
) -> pipeline.RecallResult:
    """四档检索：dense / bm25 / rrf / hybrid（RRF + 精排）。

    `rerank` 是本轮覆盖项（参数实验的「重排」轴）：`None` 表示沿用全局配置
    `settings.retrieval_rerank`，`False` 表示跳过精排、直接用融合顺序（此时
    citations 的 `score_stage` 是 `rrf` 而不是 `rerank`）。没有这个覆盖口，
    E3 实验里 rerank=true/false 两组跑出来的引用完全一样，那根轴就是装饰。
    """
    task_id = _latest_task(user_id)
    if task_id is None:
        return pipeline.RecallResult(citations=[], rows=[], elapsed_ms=0)

    question = (req.question or "").strip()
    if not question:
        # 无问题（如列举模式）按 chunk_id 顺序回传，分数置 0。
        rows = _fallback_rows(user_id, req)
        for row in rows:
            row["score"] = 0.0
        citations = [pipeline._as_citation(i + 1, row, "dense") for i, row in enumerate(rows)]
        traces = [pipeline._as_trace_row(i + 1, row, "dense") for i, row in enumerate(rows)]
        return pipeline.RecallResult(citations=citations, rows=traces, elapsed_ms=0)

    settings = get_settings()
    rewritten = runtime.rewriter().rewrite(question, history)
    vector = runtime.embedder().embed([rewritten])[0]
    runtime.ensure_dim(len(vector))
    request = pipeline.RecallRequest(
        user_id=user_id,
        task_id=task_id,
        vector=vector,
        k=req.k,
        doc_ids=list(req.doc_ids),
        kind=req.kind,
    )
    # N3：正常召回只看普通片段（`kind=chunk`）。摘要卡不参与自由竞争 —— 它是「全库概览」，
    # 与任何具体问题都不算特别近也不算远，让它自由竞争的结果是**随机地**挤掉真实片段
    # （实测问「借几本」拿到「全库共 6 份资料」）。兜底逻辑见 `_with_summary_card`。
    recall_kind = req.kind or "chunk"
    dense = runtime.store().search(
        user_id=user_id, task_id=task_id, vector=vector,
        k=max(settings.retrieval_candidate_limit, req.k),
        doc_ids=req.doc_ids, kind=recall_kind,
    )
    if not dense:
        rows = _fallback_rows(user_id, req)
        citations = [pipeline._as_citation(i + 1, row, "dense") for i, row in enumerate(rows)]
        traces = [pipeline._as_trace_row(i + 1, row, "dense") for i, row in enumerate(rows)]
        return pipeline.RecallResult(citations=citations, rows=traces, elapsed_ms=0)

    selected_mode = mode or settings.retrieval_mode
    # 本轮真正生效的重排开关：显式覆盖优先，否则沿用全局配置。
    rerank_effective = settings.retrieval_rerank if rerank is None else bool(rerank)
    diagnostics: dict[str, Any] = {
        "mode": selected_mode,
        "originalQuestion": question,
        "rewrittenQuestion": rewritten,
        "rewriteDegraded": runtime.rewriter().degraded,
        "rerankRequested": rerank,
        "rerankEffective": rerank_effective,
        "dense": [{"chunkId": row["chunk_id"], "score": row["score"]} for row in dense],
        "sparse": [],
        "rrf": [],
        "rerank": [],
    }
    if selected_mode == "dense":
        result = pipeline.recall(runtime.store(), request, stage="dense", candidates=dense)
        result.diagnostics = diagnostics
        return result

    scoped = _scoped_rows(user_id, task_id, req)
    sparse = bm25_cache.build(
        user_id, task_id, scoped, scope=f"{recall_kind}|{','.join(sorted(req.doc_ids))}",
    ).top(rewritten, settings.retrieval_candidate_limit)
    diagnostics["sparse"] = [{"chunkId": row["chunk_id"], "score": row["score"]} for row in sparse]
    if selected_mode == "bm25":
        result = pipeline.recall(runtime.store(), request, stage="sparse", candidates=sparse)
        result.diagnostics = diagnostics
        return result

    fused = reciprocal_rank_fusion(
        (dense, sparse), k=settings.retrieval_rrf_k, limit=settings.retrieval_candidate_limit,
    )
    diagnostics["rrf"] = [{"chunkId": row["chunk_id"], "score": row["score"]} for row in fused]
    if selected_mode == "rrf" or not rerank_effective:
        # rerank=false 的实验组走这条：分数阶段是 rrf，不是 rerank。
        result = pipeline.recall(runtime.store(), request, stage="rrf", candidates=fused)
        result.diagnostics = diagnostics
        _with_summary_card(result, user_id, task_id, vector, req, rewritten)
        return result

    reranker = runtime.reranker()
    ranked = reranker.rerank(rewritten, fused, req.k)
    diagnostics["rerank"] = [{"chunkId": row["chunk_id"], "score": row["score"]} for row in ranked]
    diagnostics["rerankDegraded"] = reranker.degraded
    diagnostics["degradeReason"] = reranker.reason
    # 服务只返回 top-k；未入选的候选接在后面，构成 F08 的淘汰区。
    ranked_ids = {row["chunk_id"] for row in ranked}
    candidates = ranked + [row for row in fused if row["chunk_id"] not in ranked_ids]
    result = pipeline.recall(runtime.store(), request, stage="rerank", candidates=candidates)
    result.diagnostics = diagnostics
    _with_summary_card(result, user_id, task_id, vector, req, rewritten)
    return result


def _with_summary_card(
    result: pipeline.RecallResult,
    user_id: int,
    task_id: str,
    vector: list[float],
    req: RetrieveRequest,
    question: str,
) -> None:
    """前 k 里没有任何 summary/rule 时，用最优摘要卡替换末位（N3 的检索兜底）。

    三个约束都来自提示词，别自己放宽：

    1. **保持 k 不变**：替换而不是追加 —— 多给一条会让 `len(citations) == k` 的既有断言
       与「引用条数等于 k」的语义一起失效；
    2. **被替换的那条 `retrieved` 置 false 但仍留在 rows 里**：它在 F08 的淘汰区，
       用户点开「检索过程」要能看到「这条本来进了，被摘要卡顶掉了」；
    3. **只在 rag/both 生效**：direct 不检索，压根走不到这里。

    @param result 已组装好的检索结果（原地修改）
    @param user_id 归属用户
    @param task_id 任务号
    @param vector 查询向量
    @param req 检索请求
    @param question 已改写的问题（判断是否在问全局）
    """
    if not result.citations:
        return
    if any(item.get("kind") in ("summary", "rule") for item in result.citations):
        return
    if not _wants_global(question):
        return
    card = _best_card(user_id, task_id, vector, req)
    if card is None:
        return
    citations = list(result.citations)
    rows = list(result.rows)
    keep = max(0, len(citations) - 1)
    dropped = citations[keep] if keep < len(citations) else None
    if dropped is not None:
        # 被顶掉的那条退回淘汰区：rows 里对应行的 retrieved 改 false。
        for row in rows:
            if row.get("chunk_id") == dropped.get("chunk_id"):
                row["retrieved"] = False
                break
    replacement = pipeline._as_citation(keep + 1, card, "dense")
    citations = citations[:keep] + [replacement]
    # 轨迹行也必须补上这张卡，否则 rows 里根本没有它 —— 前端「检索过程」看不到摘要卡命中，
    # 而 citations 里有，两边对不上。
    card_row = pipeline._as_trace_row(keep + 1, card, "dense")
    rows = rows[:keep] + [card_row] + rows[keep + 1 :]
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    for index, citation in enumerate(citations, start=1):
        citation["ref"] = index
    result.citations = citations
    result.rows = rows
    result.diagnostics = {
        **(result.diagnostics or {}),
        "summaryFallback": {
            "chunkId": card["chunk_id"],
            "replaced": dropped.get("chunk_id") if dropped else None,
        },
    }


def retrieve_data(
    user_id: int, req: RetrieveRequest, mode: str | None = None,
) -> dict[str, Any]:
    """检索结果；无命中时返回空引用列表，不伪造引用。

    `InternalRetrieveResult` 是 `additionalProperties: false`，只有 citations 与 rows。
    A3 的中间产物（dense/sparse/rrf/rerank 各路候选与降级原因）留在
    `RecallResult.diagnostics` 里供进程内诊断与报告使用，**不进这个响应**：
    多塞一个字段会让整个响应在 Java 侧与契约校验里被判非法。
    """
    result = retrieve(user_id, req, mode=mode)
    return {"citations": result.citations, "rows": result.rows}


def context_citations(
    user_id: int,
    question: str,
    k: int,
    history: list[dict[str, str]] | None = None,
    rerank: bool | None = None,
) -> list[dict[str, Any]]:
    """对话链路取上下文引用；供 `chat.sse_events` 复用同一套检索。

    `rerank` 由 `ChatRequest.options["rerank"]` 透传：参数实验的 rerank=false 组
    要求引用里不出现 `score_stage=rerank`，所以这个开关必须一路传到检索层。
    """
    result = retrieve(
        user_id, RetrieveRequest(question=question, k=k), history=history, rerank=rerank,
    )
    return result.citations


def task_chunks(user_id: int, task_id: str) -> list[dict[str, Any]]:
    """把该任务的切片整理成 Java 侧 {@code AiChunk} 认得的字段名。

    Java 建库轮询拿到 {@code data.chunks} 才会把片段缓存进 MySQL 的 chunk 表并对外提供
    {@code GET /api/v1/chunks}；这里少给一层，前端知识库页就永远是空列表。

    只回传本人本次任务的切片：{@code state.list_chunks} 已按 {@code (user_id, task_id)} 限定范围。
    """
    return [
        {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "doc_title": row["doc_title"],
            "heading_path": row["heading_path"],
            "text": row["excerpt"],
            "start": row["start"],
            "end": row["end"],
            "kind": row["kind"],
            "verified": row["verified"],
        }
        for row in state.list_chunks(user_id, task_id)
    ]


def index_manifest(user_id: int, embedding_model: str, chunk_size: int, overlap: int) -> dict[str, Any]:
    """按该用户最近成功任务产出索引清单，无任务时回退请求默认值。

    `summary` 字段（N3）如实反映摘要卡有没有生成：`cards = 0` 表示本次建库降级为
    「无摘要卡」（LLM 失败或 `gen_summary=false`），**不是**「还没算」。
    """
    latest = state.latest_succeeded_task(user_id)
    if latest is None:
        return {
            "status": "needs_rebuild",
            "embedding_model": embedding_model,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "doc_count": 0,
            "chunk_count": 0,
            "built_at": None,
            "sha256": "",
            "summary": None,
        }
    task_id = str(latest["task_id"])
    chunks = state.list_chunks(user_id, task_id)
    doc_ids = {row["doc_id"] for row in chunks}
    cards = [row for row in chunks if row["kind"] in ("summary", "rule")]
    summary = (
        {
            "model": embedding_model,
            "cards": len(cards),
            "kinds": sorted({row["kind"] for row in cards}),
        }
        if cards
        else None
    )
    return {
        "status": "ready" if chunks else "needs_rebuild",
        "embedding_model": embedding_model,
        "chunk_size": int(latest.get("chunk_size", chunk_size)),
        "overlap": int(latest.get("overlap", overlap)),
        # 摘要卡的 doc_id 是 "__summary__"，它不属于任何一份资料，不能算进 doc_count。
        "doc_count": len(doc_ids - {summarizer.SUMMARY_DOC_ID}),
        "chunk_count": len(chunks),
        "built_at": latest["finished_at"],
        "sha256": "",
        "summary": summary,
    }


def drop_task(user_id: int, task_id: str) -> None:
    """删除某任务在向量库里的切片（资料被删或重建前清理旧产物）。"""
    runtime.store().delete_task(user_id, task_id)


def drop_user(user_id: int) -> None:
    """删除某用户在向量库里的全部切片。"""
    runtime.store().delete_user(user_id)


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_OVERLAP",
    "SCORE_STAGES",
    "build_chunks",
    "context_citations",
    "drop_task",
    "drop_user",
    "index_manifest",
    "prompt",
    "retrieve",
    "retrieve_data",
    "run_ingest",
    "runtime",
    "task_chunks",
]
