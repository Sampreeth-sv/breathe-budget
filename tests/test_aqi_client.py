import httpx
import pytest
import respx

from app.config import Settings
from app.services.aqi_client import (
    AIR_URL,
    GEOCODE_URL,
    AirQualityClient,
    CityNotFound,
    GeoPlace,
    UpstreamError,
)

PLACE = GeoPlace(name="Delhi", country="India", latitude=28.65, longitude=77.23)


@pytest.fixture
def aq():
    return AirQualityClient(Settings())


@respx.mock
async def test_geocode_parses_and_caches(aq):
    route = respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json={"results": [{"name": "Delhi", "country": "India", "latitude": 28.65, "longitude": 77.23}]}
        )
    )
    first = await aq.geocode("Delhi")
    second = await aq.geocode("  DELHI ")
    assert first == second == PLACE
    assert route.call_count == 1


@respx.mock
async def test_geocode_unknown_city(aq):
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"generationtime_ms": 1}))
    with pytest.raises(CityNotFound):
        await aq.geocode("Nowhereville")


@respx.mock
async def test_geocode_malformed_result(aq):
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"results": [{"name": "X"}]}))
    with pytest.raises(UpstreamError):
        await aq.geocode("X")


@respx.mock
@pytest.mark.parametrize("response", [
    httpx.Response(500),
    httpx.Response(200, text="not json"),
    httpx.ConnectTimeout("slow"),
])
async def test_upstream_failures_become_upstream_error(aq, response):
    respx.get(AIR_URL).mock(side_effect=[response])
    with pytest.raises(UpstreamError):
        await aq.air_quality(PLACE)


@respx.mock
async def test_air_quality_parses_current_and_hourly(aq):
    hourly = [10.0 + h for h in range(24)]
    route = respx.get(AIR_URL).mock(
        return_value=httpx.Response(
            200, json={"current": {"time": "2026-11-20T09:00", "pm2_5": 123.4}, "hourly": {"pm2_5": hourly}}
        )
    )
    reading = await aq.air_quality(PLACE)
    assert reading.pm25 == 123.4 and reading.observed_at == "2026-11-20T09:00"
    assert len(reading.hourly) == 24
    await aq.air_quality(PLACE)
    assert route.call_count == 1  # served from cache


def test_parse_air_falls_back_to_hourly_mean():
    reading = AirQualityClient._parse_air({"current": {}, "hourly": {"pm2_5": [10, None, 30]}})
    assert reading.pm25 == 20


@pytest.mark.parametrize("data", [None, [], {}, {"current": {"pm2_5": None}, "hourly": {"pm2_5": [None]}}])
def test_parse_air_rejects_unusable_data(data):
    with pytest.raises(UpstreamError):
        AirQualityClient._parse_air(data)


def test_parse_air_drops_bad_values():
    reading = AirQualityClient._parse_air(
        {"current": {"pm2_5": -5}, "hourly": {"pm2_5": [float("nan"), -1, "x", True, 40]}}
    )
    assert reading.pm25 == 40
    assert reading.hourly[:4] == (None, None, None, None)
