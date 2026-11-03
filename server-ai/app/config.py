from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ai_provider: str = "mock"
    llm_endpoint: str = ""
    llm_model: str = "mock-model"
    embedding_endpoint: str = ""
    embedding_model: str = "mock-embedding"
    internal_token: str = "dev-internal-token"
    storage_root: str = "./storage"
    milvus_uri: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

@lru_cache
def get_settings() -> Settings:
    return Settings()
