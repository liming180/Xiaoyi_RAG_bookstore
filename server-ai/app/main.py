from __future__ import annotations
import asyncio, hashlib, time, uuid
from typing import Any, AsyncIterator
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
import json
from .config import get_settings
from .schemas.models import ChatRequest, Envelope, EvalRequest, ParseRequest, RetrieveRequest
from .core.llm.provider import provider_from_settings

app = FastAPI(title="小忆 RAG AI Service", docs_url=None, redoc_url=None)
_started = time.time()
tasks: dict[str, dict[str, Any]] = {}
documents: dict[str, dict[str, Any]] = {}
chunks: list[dict[str, Any]] = []
settings = get_settings()
provider = provider_from_settings(settings)

def envelope(data: Any = None, code: int = 0, message: str = "success") -> dict[str, Any]:
    return {"code": code, "message": message, "data": data, "timestamp": int(time.time())}

def require_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")):
    if not x_internal_token or x_internal_token != get_settings().internal_token:
        raise HTTPException(status_code=401, detail=envelope(None, 40102, "内部令牌无效"))
    return x_internal_token

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else envelope(None, exc.status_code, str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=detail)

@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content=envelope(None, 40001, "参数校验失败"))


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    return JSONResponse(status_code=400, content=envelope(None, 40001, "参数校验失败"))

def citation(index: int, doc_id: str = "D01") -> dict[str, Any]:
    text = "模拟检索片段，用于联调内部引用契约。"
    return {"ref": index, "chunk_id": f"D{index:02d}-C001", "doc_id": doc_id,
            "doc_title": "mock-document.md", "heading_path": "# 模拟章节", "excerpt": text,
            "start": 0, "end": len(text), "score": round(0.95 - index * .05, 3),
            "score_stage": "rerank", "kind": "chunk", "verified": True}

def retrieve_data(req: RetrieveRequest) -> dict[str, Any]:
    found = [c for c in chunks if (not req.doc_ids or c["doc_id"] in req.doc_ids) and (not req.kind or c["kind"] == req.kind)]
    if not found:
        found = [citation(i + 1) for i in range(req.k)]
    found = found[:req.k]
    rows = [{"rank": i + 1, **{k: v for k, v in c.items() if k != "ref"}, "retrieved": True} for i, c in enumerate(found)]
    return {"citations": found, "rows": rows}

def update_task(task_id: str, req: ParseRequest):
    task = tasks[task_id]
    task.update(status="RUNNING", stage="parsing", progress=20)
    for doc in req.documents:
        documents[doc.doc_id] = {"doc_id": doc.doc_id, "status": "PARSING", "chunk_count": 0}
    task.update(stage="splitting", progress=45)
    count = 0
    for doc in req.documents:
        text = doc.text or doc.title or doc.name or ""
        part = {"chunk_id": f"D{len(chunks)+1:02d}-C001", "doc_id": doc.doc_id, "doc_title": doc.title or doc.name,
                "heading_path": "# 模拟章节", "excerpt": text[:req.chunk_size] or "模拟片段", "start": 0,
                "end": min(len(text), req.chunk_size), "score": .9, "score_stage": "rerank", "kind": "chunk", "verified": True}
        chunks.append(part); count += 1; documents[doc.doc_id].update(status="INDEXED", chunk_count=1)
    task.update(stage="embedding", progress=70, chunk_count=count)
    task.update(stage="summarizing", progress=90)
    task.update(status="SUCCEEDED", stage="done", progress=100, finished_at=int(time.time()))

async def sse_events(req: ChatRequest) -> AsyncIterator[str]:
    started = time.perf_counter()
    def frame(event: str, data: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    for stage in ("rewriting", "retrieving", "reranking"):
        yield frame("status", {"stage": stage})
    result = retrieve_data(RetrieveRequest(question=req.question, k=req.k))
    yield frame("retrieval", {"citations": result["citations"]})
    yield frame("status", {"stage": "generating"})
    answer = ""
    async for token in provider.answer(req.question):
        answer += token
        yield frame("token", {"content": token})
    done = {"message_id": "py-m-" + uuid.uuid4().hex[:8], "usage": provider.usage(req.question, answer),
            "elapsed_ms": int((time.perf_counter() - started) * 1000), "degraded": False,
            "suggestions": ["可以继续了解吗？"]}
    if req.mode == "both":
        done["direct_message_id"] = "py-direct-" + uuid.uuid4().hex[:8]; done["direct_content"] = answer
    yield frame("done", done)

@app.post("/internal/v1/chat/stream")
async def chat_stream(req: ChatRequest, _: str = Depends(require_token)):
    return StreamingResponse(sse_events(req), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

@app.post("/internal/v1/documents/parse")
async def parse_documents(req: ParseRequest, bg: BackgroundTasks, _: str = Depends(require_token)):
    task_id = "task-" + uuid.uuid4().hex[:12]
    tasks[task_id] = {"task_id": task_id, "status": "PENDING", "stage": "parsing", "progress": 0,
                      "doc_count": len(req.documents), "chunk_count": 0, "error": "", "created_at": int(time.time()), "finished_at": None}
    bg.add_task(update_task, task_id, req)
    return envelope({"task_id": task_id, "doc_count": len(req.documents)})

@app.get("/internal/v1/ingest/{task_id}")
async def ingest(task_id: str, _: str = Depends(require_token)):
    if task_id not in tasks: raise HTTPException(404, detail=envelope(None, 40402, "任务不存在"))
    return envelope(tasks[task_id])

@app.get("/internal/v1/documents/{id}/status")
async def document_status(id: str, _: str = Depends(require_token)):
    if id not in documents: raise HTTPException(404, detail=envelope(None, 40401, "资料不存在"))
    return envelope(documents[id])

@app.get("/internal/v1/index/status")
async def index_status(_: str = Depends(require_token)):
    return envelope({"status": "ready" if chunks else "needs_rebuild", "embedding_model": settings.embedding_model,
                     "chunk_size": 180, "overlap": 30, "doc_count": len(documents), "chunk_count": len(chunks),
                     "built_at": int(time.time()) if chunks else None, "sha256": ""})

@app.post("/internal/v1/retrieve")
async def retrieve(req: RetrieveRequest, _: str = Depends(require_token)):
    return envelope(retrieve_data(req))

@app.post("/internal/v1/eval/batch")
async def eval_batch(req: EvalRequest, _: str = Depends(require_token)):
    results = []
    for case in req.cases:
        answer = f"这是针对“{case.question}”的模拟回答。"
        groups = [g.lower().split("/") for g in case.keywords.split("|")]
        passed = all(any(word in answer.lower() for word in group) for group in groups)
        results.append({"question_id": case.id, "direct_answer": answer, "direct_passed": passed,
                        "rag_answer": answer, "rag_passed": passed, "rag_sources": [], "elapsed_ms": 0})
    return envelope({"cases": results, "total": len(results), "passed_direct": sum(r["direct_passed"] for r in results),
                     "passed_rag": sum(r["rag_passed"] for r in results)})

@app.get("/internal/v1/health")
async def health(_: str = Depends(require_token)):
    return envelope({"status": "UP", "version": "0.1.0", "embedding_model": settings.embedding_model,
                     "llm_model": settings.llm_model, "uptime_seconds": int(time.time() - _started)})
