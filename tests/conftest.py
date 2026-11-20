from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.aqi_client import (
    AirQualityClient,
    AirReading,
    CityNotFound,
    GeoPlace,
    UpstreamError,
)
from app.services.llm import Explainer

# 24 hourly PM2.5 values: bad at night, cleanest at 14:00.
HOURLY = tuple(
    [180.0] * 6 + [160.0, 150.0, 140.0, 130.0, 120.0, 110.0, 105.0, 100.0]
    + [95.0] + [110.0, 130.0, 150.0, 170.0, 185.0, 190.0, 195.0, 190.0]
)[:24]
HOURLY = HOURLY[:14] + (60.0,) + HOURLY[15:]


class FakeAir(AirQualityClient):
    def __init__(self, settings: Settings, pm25: float = 150.0, fail: bool = False):
        super().__init__(settings)
        self.pm25 = pm25
        self.fail = fail
        self.geocode_calls = 0
        self.air_calls = 0

    async def geocode(self, city: str) -> GeoPlace:
        self.geocode_calls += 1
        if self.fail:
            raise UpstreamError("down")
        if city.lower() == "atlantis":
            raise CityNotFound(city)
        return GeoPlace(name=city.title(), country="India", latitude=28.6, longitude=77.2)

    async def air_quality(self, place: GeoPlace) -> AirReading:
        self.air_calls += 1
        if self.fail:
            raise UpstreamError("down")
        return AirReading(pm25=self.pm25, observed_at="2026-11-20T09:00", hourly=HOURLY)


class FakeExplainer(Explainer):
    def __init__(self, settings: Settings, result: str | None = None, enabled: bool = True):
        super().__init__(settings)
        self._result = result
        self._enabled = enabled
        self.facts: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def summarise(self, facts):
        self.facts.append(facts)
        return self._result


@pytest.fixture
def settings() -> Settings:
    return Settings(rate_limit_per_minute=1000)


@pytest.fixture
def air(settings) -> FakeAir:
    return FakeAir(settings)


@pytest.fixture
def explainer(settings) -> FakeExplainer:
    return FakeExplainer(settings, enabled=False)


@pytest.fixture
def client(settings, air, explainer):
    app = create_app(settings, air_client=air, explainer=explainer)
    with TestClient(app) as test_client:
        yield test_client


VALID_PAYLOAD = {
    "city": "Delhi",
    "household": {"adults": 2, "children": 1, "seniors": 0, "respiratory_condition": True},
    "commute_mode": "two_wheeler",
    "commute_minutes_each_way": 40,
    "cooking_fuel": "lpg",
    "heating": "none",
    "has_purifier": False,
    "outdoor_exercise_minutes": 30,
    "neighbourhood_households": 60,
}


@pytest.fixture
def payload() -> dict:
    import copy

    return copy.deepcopy(VALID_PAYLOAD)
