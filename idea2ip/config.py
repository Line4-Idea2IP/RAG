from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IDEA2IP_", env_file=".env", extra="ignore", frozen=True
    )
    mode: Literal["mock", "live"] = "mock"
    retrieval: Literal["none", "fixture", "pgvector"] = "none"
    llm_base_url: str = "http://localhost:8081/v1"
    llm_model: str = "idea2ip-vl"
    llm_timeout: float = Field(default=90, gt=0, le=300)
    llm_max_tokens: int = Field(default=2048, ge=128, le=8192)
    service_token: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    index_version: str = "idea2ip-v1"
    kure_model: str = "nlpai-lab/KURE-v1"
    embedding_url: str = ""
    min_similarity: float = Field(default=0.5, ge=0, le=1)
    top_k: int = Field(default=5, ge=1, le=20)
    legal_catalog: Path = Path("samples/legal_catalog.json")
