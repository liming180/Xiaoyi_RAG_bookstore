from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ai_provider: str = "mock"
    llm_endpoint: str = ""
    llm_model: str = "mock-model"
    embedding_endpoint: str = ""
    embedding_model: str = "mock-embedding"
    internal_token: str
    storage_root: str = "./storage"
    milvus_uri: str = ""
    # 每个入库阶段之间的停顿（毫秒）。默认 0 = 全速推进；调大后 Java 侧轮询才看得到
    # parsing → splitting → embedding → summarizing → done 的完整阶段序列。
    ingest_stage_delay_ms: int = 0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    def validate(self) -> "Settings":
        if not self.internal_token or not self.internal_token.strip():
            raise ValueError("INTERNAL_TOKEN must be nonblank")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings().validate()
