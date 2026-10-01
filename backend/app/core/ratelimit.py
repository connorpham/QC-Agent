import time
from collections import deque
from collections.abc import Callable

MAX_KEYS = 100_000


class SlidingWindowLimiter:
    """In-process limiter. Correct for a single backend process (Phase 1 deployment).

    Keys with no hits inside the window are dropped so memory stays bounded: a full sweep
    runs at most once per window, and immediately once ``max_keys`` keys are held.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = MAX_KEYS,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = clock()

    def _sweep(self, now: float) -> None:
        cutoff = now - self._window
        for key in [k for k, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]:
            del self._hits[key]
        self._last_sweep = now

    def hit(self, key: str) -> bool:
        now = self._clock()
        if now - self._last_sweep >= self._window or len(self._hits) >= self._max_keys:
            self._sweep(now)
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = self._hits[key] = deque()
        while bucket and bucket[0] <= now - self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True
