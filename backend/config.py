"""Application configuration loaded from .env file."""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    # Database
    POSTGRES_PASSWORD: str = ""
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

    # Opt-in private processing. These values select a separate local route;
    # the existing Gemini/Typhoon route remains the normal online mode.
    OFFLINE_MODE: bool = False
    OFFLINE_LLM_MODEL: str = "gemma3:4b"
    PRIVATE_DATA_DIR: str = ""
    LOCAL_OCR_PYTHON: str = ""
    LOCAL_OCR_MODELS_DIR: str = ""
    LOCAL_OCR_EASYOCR_CACHE_DIR: str = ""
    LOCAL_OCR_PAGE_TIMEOUT_SECONDS: float = 900.0
    PDF_OCR_PROVIDER: str = "typhoon"

    # Text generation provider: "ollama" (local) or "gemini" (Vertex AI).
    # Embeddings stay on Ollama regardless — only generation switches.
    LLM_PROVIDER: str = "ollama"

    # Gemini on Vertex AI (used when LLM_PROVIDER=gemini)
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    VERTEX_PROJECT: str = ""
    VERTEX_LOCATION: str = "global"
    GEMINI_MODEL: str = "gemini-2.5-flash"
    # Thinking tokens are billed as output and drawn from max_output_tokens.
    # 0 disables thinking (default); -1 lets the model decide; >0 caps the budget.
    GEMINI_THINKING_BUDGET: int = 0
    # Vertex uses a dynamic shared quota, so 429s are routine under bursts.
    # Total attempts per call, and the base for exponential backoff (seconds).
    GEMINI_MAX_RETRIES: int = 8
    GEMINI_RETRY_BASE_DELAY: float = 2.0
    # Proactive pacing: floor on the gap between calls, widened automatically
    # when the shared pool returns 429 and relaxed back on success.
    GEMINI_MIN_INTERVAL: float = 1.0
    GEMINI_MAX_INTERVAL: float = 20.0

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
    TYPHOON_OCR_RENDER_DPI: int = 300
    TYPHOON_OCR_PAGE_TIMEOUT_SECONDS: float = 240.0
    PDF_QUALITY_REOCR_ENABLED: bool = True
    PDF_QUALITY_REOCR_DPI: int = 400
    PDF_QUALITY_REOCR_MAX_PAGES: int = 20
    TYPHOON_OCR_REQUEST_TIMEOUT: float = 180.0
    TYPHOON_OCR_SLEEP_SECONDS: float = 0.7
    # When enabled, Typhoon supplies page prose and Gemini reads table cells.
    PDF_TABLE_OCR_PROVIDER: str = "typhoon"

    # Table Extraction Pipeline
    TABLE_DETECTOR_BACKEND: str = "tatr"  # "opencv" or "tatr"
    TABLE_PREPROCESS_TARGET_DPI: int = 300
    TABLE_SELF_CORRECTION_MAX_RETRIES: int = 2
    TABLE_CONFIDENCE_THRESHOLD: float = 0.4

    # DuckDB Data Warehouse
    DUCKDB_PATH: str = "warehouse.duckdb"

    # Retrieval passed to the agent. Chunks are whole OCR pages, so the
    # per-chunk budget has to be wide enough to reach an answer buried mid-page
    # (measured positions on real failures: 1376, 2077, 2206 chars in).
    VECTOR_TOP_K: int = 10
    VECTOR_CHUNK_CHARS: int = 2500

    # Agentic RAG
    AGENT_MAX_ITERATIONS: int = 5
    AGENT_TEMPERATURE: float = 0.1
    # Answer self-correction (verify the drafted Final Answer against tool
    # observations, and regenerate once if it is ungrounded / off-topic)
    AGENT_SELF_CORRECTION: bool = True
    AGENT_VERIFY_MAX_RETRIES: int = 1

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_RELOAD: bool = False
    MAX_UPLOAD_BYTES: int = 250_000_000
    PDF_LARGE_FILE_PAGE_THRESHOLD: int = 80
    PDF_OCR_BATCH_SIZE: int = 20
    PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT: int = -1
    PDF_LARGE_FILE_GENERATE_SUMMARIES: bool = False
    DOCUMENT_RAW_TEXT_LIMIT_CHARS: int = 250000
    RAW_OCR_ARTIFACT_EMBED_MAX_CHARS: int = 8000

    @model_validator(mode="after")
    def use_postgres_password(self) -> "Settings":
        """Keep app connections aligned with Docker's POSTGRES_PASSWORD."""
        if self.POSTGRES_PASSWORD:
            self.DATABASE_URL = make_url(self.DATABASE_URL).set(
                password=self.POSTGRES_PASSWORD
            ).render_as_string(hide_password=False)
            self.DATABASE_URL_SYNC = make_url(self.DATABASE_URL_SYNC).set(
                password=self.POSTGRES_PASSWORD
            ).render_as_string(hide_password=False)
        return self

    @model_validator(mode="after")
    def configure_offline_mode(self) -> "Settings":
        if not self.OFFLINE_MODE:
            return self
        from pathlib import Path
        from urllib.parse import urlparse

        def local_host(value: str) -> bool:
            host = (urlparse(value).hostname or "").lower()
            return host in {"localhost", "127.0.0.1", "::1"}

        if not local_host(self.OLLAMA_HOST):
            raise ValueError("OFFLINE_MODE requires a localhost OLLAMA_HOST")
        for name in ("DATABASE_URL", "DATABASE_URL_SYNC"):
            host = (make_url(getattr(self, name)).host or "").lower()
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(f"OFFLINE_MODE requires a localhost {name}")

        private_dir = Path(self.PRIVATE_DATA_DIR).expanduser() if self.PRIVATE_DATA_DIR else (
            Path.home() / "AppData" / "Local" / "financial-rag-private"
        )
        private_dir = private_dir.resolve()
        if any(part.lower().startswith("onedrive") for part in private_dir.parts):
            raise ValueError("PRIVATE_DATA_DIR must be outside OneDrive in OFFLINE_MODE")
        self.PRIVATE_DATA_DIR = str(private_dir)
        self.DUCKDB_PATH = str(private_dir / "warehouse.duckdb")
        self.LLM_PROVIDER = "ollama"
        self.OLLAMA_LLM_MODEL = self.OFFLINE_LLM_MODEL
        self.PDF_OCR_PROVIDER = "docling"
        self.PDF_TABLE_OCR_PROVIDER = "docling"
        self.PDF_QUALITY_REOCR_ENABLED = False
        self.GRAPH_BUILD_ENABLED = False
        self.TAVILY_API_KEY = ""
        self.OPENAI_API_KEY = ""
        self.APP_HOST = "127.0.0.1"
        self.APP_RELOAD = False
        return self

    # Hyper-Extract Knowledge Graph
    HYPEREXTRACT_LLM_URL: str = "http://localhost:11434/v1"
    HYPEREXTRACT_LLM_MODEL: str = ""
    HYPEREXTRACT_EMBED_URL: str = "http://localhost:11434/v1"
    HYPEREXTRACT_EMBED_MODEL: str = "nomic-embed-text:latest"
    HYPEREXTRACT_KA_DIR: str = "backend/knowledge_graphs"
    HYPEREXTRACT_TEMPLATE: str = "finance/ownership_graph"
    HYPEREXTRACT_LANGUAGE: str = "en"
    # Hyper-Extract currently uses an Ollama-only client. Keep it off when the
    # application is configured to use Gemini for all generation.
    GRAPH_BUILD_ENABLED: bool = False

    # External APIs
    TAVILY_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Ignore env vars that belong to other tools (e.g. POSTGRES_* consumed by
        # docker-compose) instead of raising 'extra_forbidden'.
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def ollama_extra_fields() -> dict:
    """Extra top-level fields for Ollama /api/generate based on the active model.

    Reasoning models (e.g. Qwen3, DeepSeek-R1) emit ``<think>...</think>`` before
    their answer, which corrupts the ReAct ``Action:`` / JSON parsing. We disable
    that with Ollama's ``think`` flag. Non-reasoning models ignore the absence.
    """
    model = get_settings().OLLAMA_LLM_MODEL.lower()
    if "qwen3" in model or "deepseek-r1" in model or ":thinking" in model:
        return {"think": False}
    return {}
