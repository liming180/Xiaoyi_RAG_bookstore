from typing import Any, Literal
from pydantic import BaseModel, Field

class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[HistoryTurn] = []
    mode: Literal["rag", "direct", "both"] = "rag"
    k: int = Field(3, ge=1, le=10)
    acl: list[str] = []
    # 实验通道专用覆盖项：rerank / summary / chunk_size / overlap。
    # 内部契约 InternalChatRequest 是 additionalProperties: false，YAML 里已显式声明 options；
    # 这里必须跟着收，否则 Pydantic 会静默丢弃，参数实验的「重排」轴就成了装饰。
    options: dict[str, Any] = {}
class ParseDocument(BaseModel):
    doc_id: str = Field(min_length=1)
    name: str = ""
    title: str = ""
    text: str = ""
    tags: list[str] = []
    version: str = ""
class ParseRequest(BaseModel):
    documents: list[ParseDocument] = Field(min_length=1)
    chunk_size: int = Field(180, ge=50, le=1000)
    overlap: int = Field(30, ge=0)
    submission_key: str = Field(min_length=1)
    generation: str = Field(min_length=1)
    # N3：是否生成全局摘要卡。false 时跳过 summarizing 阶段的实际生成（阶段仍上报）。
    gen_summary: bool = True
class RetrieveRequest(BaseModel):
    question: str | None = None
    k: int = Field(3, ge=1, le=10)
    chunk_size: int | None = Field(None, ge=50, le=1000)
    overlap: int | None = Field(None, ge=0)
    doc_ids: list[str] = []
    kind: Literal["chunk", "summary", "rule"] | None = None
    list_mode: bool = False
class EvalCase(BaseModel):
    id: str
    question: str
    keywords: str
class EvalRequest(BaseModel):
    cases: list[EvalCase] = Field(min_length=1)
    mode: Literal["rag", "direct", "both"]
    k: int = Field(3, ge=1, le=10)
class Citation(BaseModel):
    ref: int | str
    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    excerpt: str
    start: int
    end: int
    score: float
    score_stage: str
    kind: str
    verified: bool
class Envelope(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
    timestamp: int
