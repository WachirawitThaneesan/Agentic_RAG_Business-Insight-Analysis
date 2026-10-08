"""Ordered local Ollama embeddings using the configured embedding model."""

import httpx
import math
from typing import List
from backend.config import get_settings

settings = get_settings()
HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)


async def get_embedding(text: str) -> List[float]:
    """Get embedding vector for a single text."""
    return (await get_embeddings_batch([text]))[0]


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Embed up to 12 ordered inputs per request; reject incomplete batches.

    The current endpoint returns normalized vectors. Semantic splitting and
    retrieval both use cosine similarity, so legacy vector scales are immaterial.
    Older servers without /api/embed retain the original single-input fallback.
    """
    if not texts:
        return []
    embeddings = []
    async with httpx.AsyncClient(timeout=120.0, limits=HTTP_LIMITS, trust_env=not settings.OFFLINE_MODE) as client:
        legacy = False
        for start in range(0, len(texts), 12):
            batch = texts[start:start+12]
            if not legacy:
                response = await client.post(f"{settings.OLLAMA_HOST}/api/embed",
                    json={"model": settings.EMBED_MODEL, "input": batch, "keep_alive": "30m"})
                legacy = response.status_code in (404, 405)
                if not legacy:
                    response.raise_for_status()
                    returned = response.json().get('embeddings')
                    if not isinstance(returned, list) or len(returned) != len(batch):
                        raise ValueError('Ollama returned an incomplete embedding batch')
                    embeddings.extend(returned)
                    continue
            for text in batch:
                response = await client.post(
                    f"{settings.OLLAMA_HOST}/api/embeddings",
                    json={"model": settings.EMBED_MODEL, "prompt": text})
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
    dimension = len(embeddings[0]) if isinstance(embeddings[0], list) else 0
    if not dimension or any(not isinstance(v, list) or len(v) != dimension or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in v)
            for v in embeddings):
        raise ValueError('Ollama returned invalid embedding vectors')
    return embeddings
