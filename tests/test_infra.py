from app.ratelimit import RateLimiter, client_ip
from app.services.cache import TTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_cache_expires_and_caps_size():
    clock = Clock()
    cache = TTLCache[int](ttl_s=10, max_size=2, clock=clock)
    cache.set("a", 1)
    assert cache.get("a") == 1
    clock.now = 11
    assert cache.get("a") is None
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert len(cache) == 2 and cache.get("a") is None


def test_cache_with_zero_ttl_stores_nothing():
    cache = TTLCache[int](ttl_s=0)
    cache.set("a", 1)
    assert cache.get("a") is None


def test_rate_limiter_blocks_then_recovers():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock)
    assert limiter.allow("ip") and limiter.allow("ip")
    assert not limiter.allow("ip")
    assert limiter.allow("other")
    clock.now = 61
    assert limiter.allow("ip")


def test_client_ip_uses_last_forwarded_hop():
    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 1.2.3.4"}
        client = None

    assert client_ip(Req()) == "1.2.3.4"

    class Direct:
        headers = {}

        class client:
            host = "9.9.9.9"

    assert client_ip(Direct()) == "9.9.9.9"


def test_rate_limiter_evicts_stale_clients_when_full(monkeypatch):
    import app.ratelimit as rl

    monkeypatch.setattr(rl, "MAX_TRACKED_CLIENTS", 4)
    clock = Clock()
    limiter = RateLimiter(5, clock=clock)
    for i in range(4):
        limiter.allow(f"old{i}")
    clock.now = 120  # all existing clients are now stale
    assert limiter.allow("new")
    assert len(limiter._hits) == 1


def test_rate_limiter_drops_oldest_when_nobody_is_stale(monkeypatch):
    import app.ratelimit as rl

    monkeypatch.setattr(rl, "MAX_TRACKED_CLIENTS", 4)
    limiter = RateLimiter(5, clock=Clock())
    for i in range(4):
        limiter.allow(f"busy{i}")
    assert limiter.allow("newcomer")
    assert len(limiter._hits) <= 4 and "newcomer" in limiter._hits


def test_client_ip_falls_back_when_unknown():
    class Nothing:
        headers = {}
        client = None

    assert client_ip(Nothing()) == "unknown"
