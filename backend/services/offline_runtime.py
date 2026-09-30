"""Startup checks for the opt-in private processing mode."""

from __future__ import annotations

from pathlib import Path

import httpx

from backend.config import get_settings
from backend.services.offline_network import install_offline_network_guard


async def prepare_offline_runtime() -> None:
    settings = get_settings()
    if not settings.OFFLINE_MODE:
        return

    private_dir = Path(settings.PRIVATE_DATA_DIR)
    private_dir.mkdir(parents=True, exist_ok=True)
    python = Path(settings.LOCAL_OCR_PYTHON).expanduser()
    models = Path(settings.LOCAL_OCR_MODELS_DIR).expanduser()
    if not python.is_file():
        raise RuntimeError("OFFLINE_MODE needs LOCAL_OCR_PYTHON pointing to a Docling environment")
    if not models.is_dir():
        raise RuntimeError("OFFLINE_MODE needs prefetched LOCAL_OCR_MODELS_DIR")

    install_offline_network_guard()
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(f"{settings.OLLAMA_HOST.rstrip('/')}/api/tags")
        response.raise_for_status()
        available = {item.get("name") or item.get("model") for item in response.json().get("models", [])}
    available |= {name.removesuffix(":latest") for name in available if name}
    missing = [model for model in (settings.OLLAMA_LLM_MODEL, settings.EMBED_MODEL) if model not in available]
    if missing:
        raise RuntimeError(f"OFFLINE_MODE local Ollama models are missing: {', '.join(missing)}")
