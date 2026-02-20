from __future__ import annotations
import time
import threading

class RateLimiter:
    """
    A simple, thread-safe **token-bucket** rate limiter.

    - Token - a data structure that represents the security identity and permissions of a running process or thread.
    - "rate" means tokens per second (also the average number of allowed events per second).
    - "capacity" is the max number of tokens the bucket can hold (controls burst size).
    - Every time you call acquire(), we try to "take" 1 token.
    - If there are no tokens, we wait for them to refill over time.

    
    Usage patterns:
    1. Blocking acquire (acquire):
    - Use when a task **must happen**.
    - Thread waits until a token is available, enforcing the global rate.

    2. Non-blocking try-acquire (try_acquire):
    - Use when a task is optional or can be skipped.
    - Returns immediately with True (token acquired) or False (no token available).

    Threading context:
    - Ideal for command-line apps like rlget that download multiple files in parallel.
    - All threads share the same RateLimiter instance to coordinate request pacing.
    - Prevents exceeding rate limits and avoids server blocking while supporting bursts.

    Example:
        limiter = RateLimiter(rate=2)  # 2 requests per second

        # Blocking download (must happen)
        limiter.acquire()
        download_file(url)

        # Optional download (skip if busy)
        if limiter.try_acquire():
            download_file(url)
    """

    def __init__(self, rate: float, capacity: float | None = None):
        if rate <= 0:
            raise ValueError("rate must be > 0 (tokens per second)")
        self.rate = float(rate)
        
        # If capacity is not given, use 'rate' so we can burst up to one second worth of tokens
        self.capacity = float(capacity if capacity is not None else rate)
        
        # Start with a full bucket (burst allowed immediately)
        self._tokens = self.capacity
        self._last = time.perf_counter()    # (tracks time) stores current high-resolution time

        # Condition variable = Lock + wait/notify
        # Multiply threads will call acquire() concurrently.
        self._lock = threading.Condition()


    def _refill(self) -> None:
        """Refill tokens based on how much time has passed since last check."""
        now = time.perf_counter()
        elapsed = now - self._last
        if elapsed <= 0:
            return

        self._last = now
        # Add tokens proportional to elapsed time, but cap at capacity
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def acquire(self) -> None:
        """
        Block until at least 1 token is available, then consume it.
        This enforces the global rate across all threads sharing this limiter.
        """
        """
        If the lock is free: The thread enters the block and runs the code
        If the lock is already held:The thread blocks (waits) until the lock is released
        """
        with self._lock: 
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # If not enough tokens, wait a small amount until tokens likely exist.
                deficit = 1.0 - self._tokens
                # If you need 0.4 tokens and you refill at 5 tokens/s, ~0.08s
                wait_s = max(deficit / self.rate, 0.001)  # at least 1ms to avoid busy-waiting
                self._lock.wait(timeout=wait_s)

    def try_acquire(self) -> bool:
        """
        Non-blocking: return True if we could take a token immediately, else False.
        Useful if you want to skip instead of waiting.
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False