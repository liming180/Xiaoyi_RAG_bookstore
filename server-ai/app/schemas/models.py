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
class ParseDocument(BaseModel):
    doc_id: str = Field(min_length=1)
    name: str = ""
    title: str = ""
    text: str = ""
    tags: list[str] = []
    version: str = ""
class ParseRequest(BaseModel):
    documents: list[ParseDocument] = Field(min_length=1)
    chunk_size: int = Field(ge=50, le=1000)
    overlap: int = Field(ge=0)
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
