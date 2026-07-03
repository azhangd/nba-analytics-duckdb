"""Token-bucket rate limiter for NBA API requests."""

import threading
import time

from nba_duckdb.utils.env import positive_float, positive_int


class RateLimiter:
    """Token-bucket rate limiter.

    Default: 1 request/sec with a burst of 1 for conservative live collection.
    """

    def __init__(self, rate: float = 1.0, burst: int = 3):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Sleep for the time needed to get one token
            time.sleep(1.0 / self.rate)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now


# Global rate limiter instance for NBA API.
# burst=1 prevents rapid-fire requests at task startup; burst>1 would fire
# multiple requests back-to-back before throttling kicks in.
nba_api_limiter = RateLimiter(
    rate=positive_float("NBA_DUCKDB_NBA_API_RATE_PER_SECOND", 1.0),
    burst=positive_int("NBA_DUCKDB_NBA_API_BURST", 1),
)
