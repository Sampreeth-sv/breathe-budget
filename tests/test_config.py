import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults(monkeypatch):
    for name in ("GEMINI_API_KEY", "LLM_TIMEOUT_S", "RATE_LIMIT_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    settings = get_settings()
    assert settings.gemini_api_key is None
    assert settings.llm_timeout_s == 8.0 and settings.rate_limit_per_minute == 30


def test_reads_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "7")
    settings = get_settings()
    assert settings.gemini_api_key == "abc" and settings.rate_limit_per_minute == 7


def test_blank_key_means_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert get_settings().gemini_api_key is None


def test_garbage_and_out_of_range_values_are_safe(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "soon")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "999999999")
    monkeypatch.setenv("AQI_CACHE_TTL_S", "-5")
    settings = get_settings()
    assert settings.llm_timeout_s == 8.0
    assert settings.rate_limit_per_minute == 10_000
    assert settings.aqi_cache_ttl_s == 0
