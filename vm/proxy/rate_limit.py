import time
import threading


class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, burst: int, per_minute: int):
        self.burst = burst
        self._rate = per_minute / 60.0  # tokens per second
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Return True if request is allowed, False if rate limited."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
