from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ---- provider ----
    # mock：完全离线，用确定性假向量与模板回答，门禁的 J3/J5 走这一档。
    # real：向量化与生成都打真实服务（本机验证过智谱 open.bigmodel.cn）。
    ai_provider: str = "mock"

    # ---- LLM（OpenAI 兼容 /chat/completions）----
    llm_endpoint: str = ""
    llm_model: str = "mock-model"
    llm_api_key: str = ""
    llm_timeout_ms: int = 60000

    # ---- A3 混合检索 ----
    # hybrid：双路 + RRF + 重排；dense：保留 A2 纯向量用于四档对照。
    retrieval_mode: str = "hybrid"
    retrieval_candidate_limit: int = 20
    retrieval_rrf_k: int = 60
    retrieval_rerank: bool = True
    retrieval_rewrite: bool = True
    rerank_endpoint: str = ""
    rerank_model: str = "rerank"
    rerank_api_key: str = ""
    rerank_timeout_ms: int = 30000

    # ---- Embedding（OpenAI 兼容 /embeddings）----
    embedding_endpoint: str = ""
    embedding_model: str = "mock-embedding"
    embedding_api_key: str = ""
    # 一次请求带多少条文本。智谱 embedding-3 实测单批 8 条稳定。
    embedding_batch_size: int = 8
    # 契约不允许出现 0 维向量；真实 provider 启动时用首次响应校准，mock 固定 64 维。
    embedding_dim: int = 0
    embedding_timeout_ms: int = 30000

    internal_token: str
    storage_root: str = "./storage"

    # ---- 向量库 ----
    # 空串 = 进程内内存实现（单测与 mock 档用）。真实环境填 http://milvus:19530。
    milvus_uri: str = ""
    milvus_collection: str = "xiaoyi_chunks"

    # 每个入库阶段之间的停顿（毫秒）。默认 0 = 全速推进；调大后 Java 侧轮询才看得到
    # parsing → splitting → embedding → summarizing → done 的完整阶段序列。
    ingest_stage_delay_ms: int = 0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    def validate(self) -> "Settings":
        if not self.internal_token or not self.internal_token.strip():
            raise ValueError("INTERNAL_TOKEN must be nonblank")
        if self.ai_provider.lower() == "real":
            if not self.embedding_endpoint.strip():
                raise ValueError("EMBEDDING_ENDPOINT must be set when AI_PROVIDER=real")
            if not self.embedding_model.strip():
                raise ValueError("EMBEDDING_MODEL must be set when AI_PROVIDER=real")
            if not self.llm_endpoint.strip():
                raise ValueError("LLM_ENDPOINT must be set when AI_PROVIDER=real")
        if self.embedding_batch_size < 1:
            raise ValueError("EMBEDDING_BATCH_SIZE must be >= 1")
        if self.retrieval_mode not in ("dense", "bm25", "rrf", "hybrid"):
            raise ValueError("RETRIEVAL_MODE must be dense, bm25, rrf, or hybrid")
        if self.retrieval_candidate_limit < 1:
            raise ValueError("RETRIEVAL_CANDIDATE_LIMIT must be >= 1")
        if self.retrieval_rrf_k < 1:
            raise ValueError("RETRIEVAL_RRF_K must be >= 1")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings().validate()
