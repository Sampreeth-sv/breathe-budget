"""Application settings, read once from environment variables.

Secrets (the Gemini API key) are only ever read from the environment and are
never logged or returned to clients.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _float_env(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return min(high, max(low, value))


def _int_env(name: str, default: int, low: int, high: int) -> int:
    return int(_float_env(name, default, low, high))


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    llm_timeout_s: float = 15.0
    http_timeout_s: float = 6.0
    aqi_cache_ttl_s: int = 900
    geocode_cache_ttl_s: int = 86_400
    rate_limit_per_minute: int = 30
    max_body_bytes: int = 8_192


@lru_cache
def get_settings() -> Settings:
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        llm_timeout_s=_float_env("LLM_TIMEOUT_S", 15.0, 1.0, 60.0),
        http_timeout_s=_float_env("HTTP_TIMEOUT_S", 6.0, 1.0, 30.0),
        aqi_cache_ttl_s=_int_env("AQI_CACHE_TTL_S", 900, 0, 86_400),
        geocode_cache_ttl_s=_int_env("GEOCODE_CACHE_TTL_S", 86_400, 0, 604_800),
        rate_limit_per_minute=_int_env("RATE_LIMIT_PER_MINUTE", 30, 1, 10_000),
    )
