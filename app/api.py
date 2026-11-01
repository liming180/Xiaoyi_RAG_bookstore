"""FastAPI 路由层：知识库、对话、检索过程、批量对照、片段浏览。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import batch, chat, chunking, judging, prompting, session, store
from .settings import (
    ALLOWED_SUFFIXES, AppError, DATA_DIR, K_DEFAULT, K_MAX, K_MIN, MAX_UPLOAD_BYTES,
    ROOT, WEB_DIST, WEB_ENTRY, has_keys, is_mock, load_config, save_config_patch,
    set_runtime_keys,
)

app = FastAPI(title="星河读书会个人资料助手", version="1.0")


def _fail(exc: AppError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- 状态
@app.get("/api/status")
def api_status() -> dict[str, Any]:
    cfg = load_config()
    payload = store.status()
    payload.update({
        "session": session.snapshot(),
        "has_keys": has_keys(),
        "provider": cfg.get("provider", "mock"),
        "mock": is_mock(cfg),
        "k_range": [K_MIN, K_MAX],
        "config": {
            "model": cfg.get("model", ""),
            "embedding_model": cfg.get("embedding_model", ""),
            "endpoint": cfg.get("endpoint", ""),
            "embedding_endpoint": cfg.get("embedding_endpoint", ""),
        },
        "examples": [item["question"] for item in judging.load_questions()[:4]],
    })
    return payload


# ---------------------------------------------------------------- 资料
@app.get("/api/docs")
def api_docs() -> dict[str, Any]:
    cfg = load_config()
    size, overlap = cfg.get("chunk_size", 180), cfg.get("chunk_overlap", 30)
    return {"docs": chunking.doc_stats(DATA_DIR, size, overlap)}


@app.post("/api/docs/upload")
async def api_upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    added, skipped = [], []
    for upload in files:
        name = Path(upload.filename or "").name
        if not name or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            skipped.append(f"{name or '未命名'}：只支持 .md / .txt")
            continue
        payload = await upload.read()
        if len(payload) > MAX_UPLOAD_BYTES:
            skipped.append(f"{name}：超过 2MB")
            continue
        try:
            text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            skipped.append(f"{name}：不是 UTF-8 编码")
            continue
        if not text.strip():
            skipped.append(f"{name}：没有正文")
            continue
        (DATA_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        added.append(name)
    return {"added": added, "skipped": skipped, "docs": api_docs()["docs"]}


@app.delete("/api/docs/{name}")
def api_delete(name: str) -> dict[str, Any]:
    safe = Path(name).name
    target = DATA_DIR / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"找不到资料 {safe}")
    target.unlink()
    return {"ok": True, "deleted": safe, "docs": api_docs()["docs"]}


@app.get("/api/docs/{name}/content")
def api_doc_content(name: str) -> dict[str, Any]:
    safe = Path(name).name
    target = DATA_DIR / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"找不到资料 {safe}")
    text = chunking.read_doc(target)
    return {"name": safe, "chars": len(text), "text": text}


# ---------------------------------------------------------------- 建库
@app.post("/api/index")
def api_index() -> dict[str, Any]:
    try:
        store.build_index_async()
    except AppError as exc:
        raise _fail(exc) from None
    return {"started": True, "state": store.build_state()}


@app.get("/api/index/progress")
def api_index_progress() -> dict[str, Any]:
    return store.build_state()


# ---------------------------------------------------------------- 片段浏览（拓展B）
@app.get("/api/chunks")
def api_chunks(source: str | None = None, q: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    size, overlap = cfg.get("chunk_size", 180), cfg.get("chunk_overlap", 30)
    chunks, _ = chunking.load_chunks(DATA_DIR, size, overlap)
    keyword = (q or "").strip()
    rows = []
    for chunk in chunks:
        if source and chunk["source"] != source:
            continue
        if keyword and keyword not in chunk["text"]:
            continue
        rows.append({
            "chunk_id": chunk["chunk_id"],
            "source": chunk["source"],
            "start": chunk["start"],
            "end": chunk["end"],
            "verified": chunk["verified"],
            "text": chunk["text"],
            "position": f'第 {chunk["start"] + 1} 字至第 {chunk["end"]} 字',
        })
    return {"chunks": rows, "size": size, "overlap": overlap, "total": len(rows)}


# ---------------------------------------------------------------- 对话
class ChatIn(BaseModel):
    question: str
    mode: str = "rag"
    k: int = K_DEFAULT


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict[str, Any]:
    try:
        result = chat.chat(body.question, body.mode, body.k)
    except AppError as exc:
        raise _fail(exc) from None
    result["session"] = session.snapshot()
    return result


class ParamsIn(BaseModel):
    mode: str | None = None
    k: int | None = None


@app.post("/api/session/params")
def api_params(body: ParamsIn) -> dict[str, Any]:
    try:
        state = session.set_params(body.mode, body.k)
    except AppError as exc:
        raise _fail(exc) from None
    return state


@app.post("/api/session/new")
def api_new_session() -> dict[str, Any]:
    return session.new_session()


@app.get("/api/logs/last")
def api_logs_last() -> dict[str, Any]:
    return store.last_log()


# ---------------------------------------------------------------- 批量对照
class BatchIn(BaseModel):
    k: int | None = None


@app.post("/api/batch/run")
def api_batch_run(body: BatchIn | None = None) -> dict[str, Any]:
    try:
        batch.run_batch_async(body.k if body else None)
    except AppError as exc:
        raise _fail(exc) from None
    return {"started": True, "state": batch.batch_state()}


@app.get("/api/batch/progress")
def api_batch_progress() -> dict[str, Any]:
    return batch.batch_state()


@app.post("/api/batch/export")
def api_batch_export() -> dict[str, Any]:
    try:
        path = batch.export_csv()
    except AppError as exc:
        raise _fail(exc) from None
    return {"path": path, "name": Path(path).name}


@app.get("/api/batch/questions")
def api_batch_questions() -> dict[str, Any]:
    try:
        items = judging.load_eval_set()
    except AppError as exc:
        raise _fail(exc) from None
    return {"questions": items}


# ---------------------------------------------------------------- 配置与密钥
class KeysIn(BaseModel):
    chat_key: str = ""
    embed_key: str = ""


@app.post("/api/keys")
def api_keys(body: KeysIn) -> dict[str, Any]:
    set_runtime_keys(body.chat_key, body.embed_key)
    return {"ok": True, "has_keys": has_keys()}


class ConfigIn(BaseModel):
    provider: str | None = None
    endpoint: str | None = None
    model: str | None = None
    embedding_endpoint: str | None = None
    embedding_model: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    top_k: int | None = None


@app.post("/api/config")
def api_config(body: ConfigIn) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "chunk_size" in patch and not 50 <= patch["chunk_size"] <= 1000:
        raise HTTPException(status_code=400, detail="片段长度须在 50 至 1000 之间。")
    if "chunk_overlap" in patch:
        size = patch.get("chunk_size", load_config().get("chunk_size", 180))
        if not 0 <= patch["chunk_overlap"] < size:
            raise HTTPException(status_code=400, detail="重叠字数须满足 0 <= 重叠 < 片段长度。")
    try:
        cfg = save_config_patch(patch)
    except AppError as exc:
        raise _fail(exc) from None
    return {"ok": True, "config": cfg, "status": api_status()}


# ---------------------------------------------------------------- 静态页面
# 前端已迁到 Vue 3 + Vite：源码在 frontend/src，构建产物在 frontend/dist。
# 运行时只服务 dist —— index.html 与 /static/assets/*。
# 旧的 web/ 目录已删除（与 frontend/ 冲突）。
_MISSING_DIST = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>前端尚未构建</title>
<style>
body{font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;background:#f8f9f7;
color:#354740;display:grid;place-items:center;height:100vh;margin:0}
.box{background:#fff;border:1px solid #e2e8e2;border-radius:16px;padding:26px 30px;
max-width:560px;box-shadow:0 8px 24px rgba(37,62,56,.06)}
h1{font-size:17px;color:#253e38;margin:0 0 10px}
code{background:#eaf2ec;color:#1c4d3e;border-radius:6px;padding:1px 6px;
font-family:"Cascadia Mono",Consolas,monospace}
p{font-size:13px;line-height:1.8;margin:8px 0}
</style></head><body><div class="box">
<h1>前端产物缺失</h1>
<p>没有找到 <code>frontend/dist/index.html</code>。请先在 <code>frontend</code> 目录执行一次构建：</p>
<p><code>cd frontend</code><br><code>npm install</code><br><code>npm run build</code></p>
<p>构建完成后刷新本页即可。后端接口（<code>/api/*</code>）不受影响，可直接用于命令行或自检。</p>
</div></body></html>"""


@app.get("/")
def index_page() -> Any:
    if not WEB_ENTRY.exists():
        return HTMLResponse(content=_MISSING_DIST, status_code=503)
    return FileResponse(WEB_ENTRY)


# check_dir=False：dist 尚未构建时不能让 StaticFiles 在 import 阶段抛 RuntimeError，
# 否则 run.cmd 与 tools/selfcheck.py 会因为「前端没构建」而整体起不来。
app.mount("/static", StaticFiles(directory=str(WEB_DIST), check_dir=False), name="static")


@app.exception_handler(AppError)
def app_error_handler(_request, exc: AppError) -> JSONResponse:      # noqa: ANN001
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def main() -> None:      # pragma: no cover - 便捷入口
    import uvicorn

    port = int(load_config().get("port", 8765))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":      # pragma: no cover
    main()
