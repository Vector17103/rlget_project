import time
from rlget.rate_limiter import RateLimiter

def test_rate_limiter_basic_throughput():
    # A limiter at 5 tokens/sec allows a burst up to capacity (5), then paces.
    rl = RateLimiter(rate=5.0)
    start = time.perf_counter()

    # Consume 10 tokens. The first ~5 are immediate (capacity), the rest are paced.
    for _ in range(10):
        rl.acquire()

    elapsed = time.perf_counter() - start
    # Expect at least ~1 second of pacing (we allow tolerance for timing variance).
    assert elapsed >= 1.0