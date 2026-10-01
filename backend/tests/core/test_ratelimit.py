from app.core.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limit_and_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is False
    assert limiter.hit("other-ip") is True
    clock.now += 61
    assert limiter.hit("ip") is True


def test_stale_keys_are_dropped() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("stale-ip") is True
    clock.now += 61
    assert limiter.hit("fresh-ip") is True
    assert "stale-ip" not in limiter._hits
    assert set(limiter._hits) == {"fresh-ip"}


def test_key_cap_triggers_an_early_sweep() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock, max_keys=2)
    assert limiter.hit("x") is True
    clock.now += 10
    assert limiter.hit("a") is True
    clock.now += 50  # periodic sweep runs here and drops "x"
    assert limiter.hit("b") is True
    assert set(limiter._hits) == {"a", "b"}
    clock.now += 11  # "a" is stale; the next periodic sweep is not due yet
    assert limiter.hit("c") is True  # key cap reached -> early sweep drops "a"
    assert set(limiter._hits) == {"b", "c"}
