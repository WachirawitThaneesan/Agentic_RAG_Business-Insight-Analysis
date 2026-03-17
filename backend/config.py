"""Application configuration loaded from .env file."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5436/ragdb"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5436/ragdb"
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 5

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Ollama
    OLLAMA_HOST: str = "http://localhost:11434"
    EMBED_MODEL: str = "nomic-embed-text:latest"
    OLLAMA_LLM_MODEL: str = "llama3.1:8b"

    # Typhoon OCR
    TYPHOON_API_KEY: str = ""
    TYPHOON_OCR_API_KEY: str = ""
    TYPHOON_OCR_ENDPOINT: str = "https://api.opentyphoon.ai/v1/ocr"
    TYPHOON_OCR_MODEL: str = "typhoon-ocr"
    TYPHOON_OCR_TASK_TYPE: str = "default"
    TYPHOON_OCR_MAX_TOKENS: int = 16384
    TYPHOON_OCR_TEMPERATURE: float = 0.1
    TYPHOON_OCR_TOP_P: float = 0.6
    TYPHOON_OCR_REPETITION_PENALTY: float = 1.2

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_RELOAD: bool = False
    PDF_LARGE_FILE_PAGE_THRESHOLD: int = 80
    PDF_OCR_BATCH_SIZE: int = 20
    PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT: int = 25
    PDF_LARGE_FILE_GENERATE_SUMMARIES: bool = False
    DOCUMENT_RAW_TEXT_LIMIT_CHARS: int = 250000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
