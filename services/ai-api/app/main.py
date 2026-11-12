"""应用装配：创建 FastAPI、挂路由、注册异常处理器、启动钩子。

业务逻辑全部下沉到 app/services/，本文件只做接线。
鉴权头 X-Internal-Token 与用户头 X-User-Id 的校验实现见 app/api/deps.py。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .api.deps import envelope
from .api.routes import router
from .services import state


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时建表并把重启前遗留的未完成任务标记为失败。"""
    state.initialize()
    state.recover_interrupted()
    yield
    state.close()


def create_app() -> FastAPI:
    """按统一配置装配应用实例。"""
    application = FastAPI(title="小忆 RAG AI Service", docs_url=None, redoc_url=None, lifespan=lifespan)
    application.include_router(router)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """HTTPException 的 detail 已是信封时原样返回。"""
        detail = exc.detail if isinstance(exc.detail, dict) else envelope(None, exc.status_code, str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=detail)

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        """请求参数校验失败统一返回 40001。"""
        return JSONResponse(status_code=400, content=envelope(None, 40001, "参数校验失败"))

    @application.exception_handler(ValidationError)
    async def validation_handler(_request: Request, _exc: ValidationError) -> JSONResponse:
        """模型校验失败同样返回 40001。"""
        return JSONResponse(status_code=400, content=envelope(None, 40001, "参数校验失败"))

    return application


app = create_app()
