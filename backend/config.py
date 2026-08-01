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
    TYPHOON_OCR_REQUEST_TIMEOUT: float = 180.0
    TYPHOON_OCR_SLEEP_SECONDS: float = 0.7

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
    PDF_LARGE_FILE_PAGE_THRESHOLD: int = 80
    PDF_OCR_BATCH_SIZE: int = 20
    PDF_RAW_OCR_PAGE_ARTIFACT_LIMIT: int = -1
    PDF_LARGE_FILE_GENERATE_SUMMARIES: bool = False
    DOCUMENT_RAW_TEXT_LIMIT_CHARS: int = 250000
    RAW_OCR_ARTIFACT_EMBED_MAX_CHARS: int = 8000

    # Hyper-Extract Knowledge Graph
    HYPEREXTRACT_LLM_URL: str = "http://localhost:11434/v1"
    HYPEREXTRACT_LLM_MODEL: str = "qwen2.5:14b"
    HYPEREXTRACT_EMBED_URL: str = "http://localhost:11434/v1"
    HYPEREXTRACT_EMBED_MODEL: str = "nomic-embed-text:latest"
    HYPEREXTRACT_KA_DIR: str = "backend/knowledge_graphs"
    HYPEREXTRACT_TEMPLATE: str = "finance/ownership_graph"
    HYPEREXTRACT_LANGUAGE: str = "en"

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
