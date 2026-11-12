"""内部接口共用的依赖：响应信封、内部令牌校验、用户身份校验。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Header, HTTPException

from ..config import get_settings

# 服务启动时刻，用于 health 接口计算运行时长。
STARTED_AT = time.time()


def envelope(data: Any = None, code: int = 0, message: str = "success") -> dict[str, Any]:
    """统一响应信封，字段与 docs/api/envelope.schema.json 保持一致。"""
    return {"code": code, "message": message, "data": data, "timestamp": int(time.time())}


def require_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> str:
    """校验内部令牌，失败返回 40102。"""
    if not x_internal_token or x_internal_token != get_settings().internal_token:
        raise HTTPException(status_code=401, detail=envelope(None, 40102, "内部令牌无效"))
    return x_internal_token


def require_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> int:
    """解析用户身份，要求 X-User-Id 为正整数串，缺失或非法返回 40001。"""
    raw = (x_user_id or "").strip()
    if not raw or not raw.isdigit():
        raise HTTPException(status_code=400, detail=envelope(None, 40001, "缺少或非法的用户标识 X-User-Id"))
    user_id = int(raw)
    if user_id <= 0:
        raise HTTPException(status_code=400, detail=envelope(None, 40001, "用户标识 X-User-Id 必须为正整数"))
    return user_id
