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
    #
    # 兼容 milvus-lite：pymilvus 3.x 在 import 时就会解析同名环境变量 MILVUS_URI，
    # 并强校验必须是 http(s):// 形式（见 pymilvus/orm/connections.py 的
    # __parse_address_from_uri）。所以内嵌模式不能用 MILVUS_URI 传文件路径，
    # 改由 XIAOYI_MILVUS_URI 传入，优先级更高；两者都没配才回落内存实现。
    milvus_uri: str = ""
    milvus_collection: str = "xiaoyi_chunks"

    def resolved_milvus_uri(self) -> str:
        """取实际使用的向量库地址。

        优先 XIAOYI_MILVUS_URI（milvus-lite 的文件路径走这条），
        其次才是的 MILVUS_URI（独立 Milvus 服务的 http 地址）。
        """
        import os as _os
        return (_os.getenv("XIAOYI_MILVUS_URI") or self.milvus_uri).strip()

    # Milvus 凭据。开启 authorizationEnabled 后必须给，否则连接被拒（code=2）。
    # 默认留空 = 不带凭据连接（兼容未开鉴权的本地环境与 CI）。
    # 注意：镜像出厂默认密码是 "Milvus" 而不是空串，详见 tools/setup_milvus_auth.py。
    milvus_user: str = ""
    milvus_password: str = ""

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
