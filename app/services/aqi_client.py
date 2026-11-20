"""Geocoding and air-quality lookups via Open-Meteo (free, no API key).

Both lookups use a shared async client with a hard timeout and a TTL cache so a
burst of requests for the same city costs one upstream call. Upstream failures
raise ``UpstreamError``; the caller decides how to degrade.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.services.cache import TTLCache

log = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


class UpstreamError(RuntimeError):
    """The air-quality or geocoding provider failed or returned bad data."""


class CityNotFound(LookupError):
    """The geocoder knows no place with that name."""


@dataclass(frozen=True)
class GeoPlace:
    name: str
    country: str | None
    latitude: float
    longitude: float


@dataclass(frozen=True)
class AirReading:
    pm25: float
    observed_at: str | None
    hourly: tuple[float | None, ...] = field(default_factory=tuple)  # local hours 0-23


def _normalise(city: str) -> str:
    folded = unicodedata.normalize("NFKC", city).casefold()
    return " ".join(folded.split())


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and value >= 0 else None  # drops NaN


class AirQualityClient:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_s),
            headers={"User-Agent": "breathe-budget/1.0"},
        )
        self._geo_cache: TTLCache[GeoPlace] = TTLCache(settings.geocode_cache_ttl_s)
        self._air_cache: TTLCache[AirReading] = TTLCache(settings.aqi_cache_ttl_s)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def geocode(self, city: str) -> GeoPlace:
        key = _normalise(city)
        cached = self._geo_cache.get(key)
        if cached:
            return cached
        data = await self._get_json(
            GEOCODE_URL, {"name": city, "count": 1, "language": "en", "format": "json"}
        )
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            raise CityNotFound(city)
        first = results[0]
        try:
            place = GeoPlace(
                name=str(first["name"])[:80],
                country=str(first["country"])[:80] if first.get("country") else None,
                latitude=float(first["latitude"]),
                longitude=float(first["longitude"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamError("unexpected geocoder response") from exc
        self._geo_cache.set(key, place)
        return place

    async def air_quality(self, place: GeoPlace) -> AirReading:
        key = f"{place.latitude:.2f},{place.longitude:.2f}"
        cached = self._air_cache.get(key)
        if cached:
            return cached
        data = await self._get_json(
            AIR_URL,
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "current": "pm2_5",
                "hourly": "pm2_5",
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
        reading = self._parse_air(data)
        self._air_cache.set(key, reading)
        return reading

    @staticmethod
    def _parse_air(data: object) -> AirReading:
        if not isinstance(data, dict):
            raise UpstreamError("unexpected air-quality response")
        current = data.get("current") or {}
        hourly_raw = (data.get("hourly") or {}).get("pm2_5") or []
        hourly = tuple(_number(v) for v in hourly_raw[:24])
        pm25 = _number(current.get("pm2_5"))
        if pm25 is None:
            valid = [v for v in hourly if v is not None]
            if not valid:
                raise UpstreamError("no PM2.5 data available")
            pm25 = sum(valid) / len(valid)
        observed = current.get("time")
        return AirReading(
            pm25=pm25,
            observed_at=str(observed)[:32] if observed else None,
            hourly=hourly,
        )

    async def _get_json(self, url: str, params: dict[str, object]) -> object:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("upstream call failed: %s", type(exc).__name__)
            raise UpstreamError("upstream provider unavailable") from exc
