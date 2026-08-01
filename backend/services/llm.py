"""Unified text-generation layer for the agent.

Every prompt in the system goes through :func:`generate`, which routes to the
provider named by ``LLM_PROVIDER``:

  ``ollama``  – local model via ``/api/generate`` (default; free, slow on 4GB VRAM)
  ``gemini``  – Gemini on Vertex AI (pay-per-token, far stronger at Thai prose)

Keeping the call sites provider-agnostic means switching models for an eval run
is an ``.env`` edit, not a code change — and lets us A/B the local 14B against a
hosted model on the same golden set.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

import httpx

from backend.config import get_settings, ollama_extra_fields

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)

_DEFAULT_MAX_TOKENS = 1024

# The Vertex client is expensive to build (credential exchange), so keep one.
_genai_client = None

# Running token tally for the process. Hosted models bill per token, so an eval
# run needs to report what it actually spent, not an estimate.
usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}


def reset_usage() -> None:
    for k in usage:
        usage[k] = 0


def usage_cost(input_price_per_m: float, output_price_per_m: float) -> float:
    """Dollar cost of the tokens counted so far, at the given per-1M rates."""
    return (
        usage["input_tokens"] * input_price_per_m / 1e6
        + usage["output_tokens"] * output_price_per_m / 1e6
    )


def _get_genai_client():
    """Lazily build the Vertex AI client, caching it for the process."""
    global _genai_client
    if _genai_client is not None:
        return _genai_client

    import os

    from google import genai

    # Point the Google auth library at the service-account key. Set here rather
    # than relying on a shell export so a plain `python -m ...` run works.
    cred_path = getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", "")
    if cred_path and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path

    _genai_client = genai.Client(
        vertexai=True,
        project=settings.VERTEX_PROJECT,
        location=settings.VERTEX_LOCATION,
    )
    return _genai_client


async def _generate_ollama(prompt: str, temperature: float, max_tokens: int) -> str:
    async with httpx.AsyncClient(timeout=600.0, limits=HTTP_LIMITS) as client:
        resp = await client.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
                **ollama_extra_fields(),
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()


# Vertex serves Gemini from a *dynamic shared quota* pool rather than a fixed
# per-project RPM, so a burst (this agent fires ~3 calls per question) can be
# refused with 429 even well inside any published limit. Google's own guidance
# is to back off and retry; these are transient, not real failures.
_RETRYABLE_CODES = (429, 500, 502, 503, 504)


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in _RETRYABLE_CODES:
        return True
    text = str(exc)
    return any(str(c) in text for c in _RETRYABLE_CODES) or "RESOURCE_EXHAUSTED" in text


class _Throttle:
    """Adaptive minimum spacing between Gemini calls.

    Retrying after a 429 is reactive — it only pays the cost once the request
    has already been refused, and a whole eval question can be lost when every
    retry lands in the same busy window. Pacing is the proactive half: hold a
    floor on the gap between calls, widen it when the pool pushes back, and let
    it relax again while requests are landing cleanly.
    """

    def __init__(self, base: float, ceiling: float) -> None:
        self._base = base
        self._ceiling = ceiling
        self._interval = base
        self._last = 0.0
        self._lock: Optional[asyncio.Lock] = None

    async def wait(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = asyncio.get_running_loop().time()
            gap = now - self._last
            if gap < self._interval:
                await asyncio.sleep(self._interval - gap)
            self._last = asyncio.get_running_loop().time()

    def penalise(self) -> None:
        """A 429 means we are going too fast — widen the floor."""
        self._interval = min(self._ceiling, max(self._base, self._interval) * 1.8)

    def relax(self) -> None:
        """Requests are landing; drift back toward the base interval."""
        if self._interval > self._base:
            self._interval = max(self._base, self._interval * 0.9)


_throttle: Optional[_Throttle] = None


def _get_throttle() -> _Throttle:
    global _throttle
    if _throttle is None:
        _throttle = _Throttle(
            base=getattr(settings, "GEMINI_MIN_INTERVAL", 1.0),
            ceiling=getattr(settings, "GEMINI_MAX_INTERVAL", 20.0),
        )
    return _throttle


async def _generate_gemini(prompt: str, temperature: float, max_tokens: int) -> str:
    from google.genai import types

    # Gemini 3.x "thinks" by default and those thought tokens are billed as
    # output *and* drawn from max_output_tokens — a 100-token budget spent 92 on
    # thinking and truncated the answer to 4. Reasoning traces also corrupt the
    # ReAct ``Action:`` JSON parsing. So thinking is off unless asked for.
    budget = getattr(settings, "GEMINI_THINKING_BUDGET", 0)
    thinking = types.ThinkingConfig(thinking_budget=budget) if budget >= 0 else None

    client = _get_genai_client()
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=thinking,
    )

    attempts = max(1, getattr(settings, "GEMINI_MAX_RETRIES", 8))
    base_delay = getattr(settings, "GEMINI_RETRY_BASE_DELAY", 2.0)
    throttle = _get_throttle()
    for attempt in range(attempts):
        await throttle.wait()
        try:
            resp = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL, contents=prompt, config=config
            )
            throttle.relax()
            break
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            throttle.penalise()
            if attempt == attempts - 1:
                raise
            # Exponential backoff with jitter, so a burst of parallel callers
            # doesn't retry in lockstep and re-trigger the same contention.
            delay = base_delay * (2 ** attempt) * (0.5 + random.random())
            logger.warning(
                "Gemini %s — retry %d/%d in %.1fs (pace %.1fs)",
                type(exc).__name__, attempt + 1, attempts - 1, delay, throttle._interval,
            )
            await asyncio.sleep(delay)

    u = getattr(resp, "usage_metadata", None)
    if u is not None:
        usage["calls"] += 1
        usage["input_tokens"] += getattr(u, "prompt_token_count", 0) or 0
        usage["output_tokens"] += getattr(u, "candidates_token_count", 0) or 0
        usage["thinking_tokens"] += getattr(u, "thoughts_token_count", 0) or 0

    return (resp.text or "").strip()


async def generate(
    prompt: str,
    *,
    temperature: Optional[float] = None,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> str:
    """Generate text with the configured provider.

    Returns an empty string on failure — callers already treat "" as "the model
    gave me nothing", so a provider outage degrades the same way a local
    timeout does instead of raising through the ReAct loop.
    """
    if temperature is None:
        temperature = getattr(settings, "AGENT_TEMPERATURE", 0.1)

    provider = (settings.LLM_PROVIDER or "ollama").lower()
    try:
        if provider == "gemini":
            result = await _generate_gemini(prompt, temperature, max_tokens)
        else:
            result = await _generate_ollama(prompt, temperature, max_tokens)
    except Exception as exc:
        logger.error("LLM call failed (provider=%s): %s", provider, exc)
        return ""

    logger.info("LLM response (%s, %d chars): %s", provider, len(result), result[:300])
    return result


def active_model() -> str:
    """Human-readable name of the model currently in use (for eval metadata)."""
    provider = (settings.LLM_PROVIDER or "ollama").lower()
    if provider == "gemini":
        return f"gemini:{settings.GEMINI_MODEL}"
    return f"ollama:{settings.OLLAMA_LLM_MODEL}"
