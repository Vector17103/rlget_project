from __future__ import annotations
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, List, Dict

# ThreadPoolExecutor runs downloads in parallel
# as_completed() → yields results as soon as each finishes, not in order

# We use Python's standard library HTTP client:
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# HTTPError → server responded with error code
# URLError → network-level failures (DNS, TLS, etc.)

from .rate_limiter import RateLimiter
from .utils import guess_filename, dedupe_path

# These HTTP status codes are considered temporary problems worth retrying.
RETRIABLE_STATUS = {429, 500, 502, 503, 504}

# @dataclass autogenrates: __init__, __repr__, and equality helpers.
@dataclass
class Result:
    """
    Represents the outcome of downloading a single URL.
    - url:       which URL we tried
    - ok:        did it succeed?
    - path:      where the file was saved (if success)
    - status:    HTTP status code if known (e.g., 200, 503)
    - attempts:  how many times we tried
    - error:     final error message (if failed)
    """
    url: str
    ok: bool
    path: Optional[Path]
    status: Optional[int]
    attempts: int
    error: Optional[str]

class DownloadManager:
    """
    Coordinates multiple downloads in parallel while:
      - respecting a global rate limit (shared token-bucket)
      - retrying politely on transient errors with exponential backoff
      - applying per-request timeouts
      - saving to disk with safe filenames
    """

    def __init__(
        self,
        output_dir: Path,
        rate: float = 5.0,
        concurrency: int = 4,
        retries: int = 3,
        timeout: float = 20.0,
        user_agent: Optional[str] = None,
        no_clobber: bool = False,
        verbose: bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Converts input to a Path, and ensures directory exists, safe even if already created

        self.retries = retries
        self.timeout = timeout
        self.user_agent = user_agent or "rlget/0.1 (+https://example.local)"
        # Identifies the app, helps avoid blocks, and is required by many servers

        self.no_clobber = no_clobber
        self.verbose = verbose

        # One limiter shared by all threads enforces requests/sec
        self._limiter = RateLimiter(rate=rate, capacity=max(rate, 1.0))
        # Thread pool controls parallelism, max is 4 (concurrency)
        self._pool = ThreadPoolExecutor(max_workers=concurrency)
        # Ensure logs from multiple threads don't interleave
        self._print_lock = threading.Lock()

    def close(self):
        """Shut down the thread pool gracefully (Waits for all downloads)."""
        self._pool.shutdown(wait=True)

    def _log(self, msg: str):
        """Print only if verbose mode is on, and serialize prints across threads."""
        if self.verbose:
            with self._print_lock:
                print(msg, flush=True)

    def _sleep_backoff(self, attempt: int, retry_after: Optional[float]):
        """
        Wait before retrying:
          - If server told us Retry-After: X, we sleep X seconds.
          - Else we use exponential backoff with jitter:
              delay = base * 2^(attempt-1) + small_random
        """
        if retry_after is not None:
            delay = float(retry_after)
        else:
            base = 0.5  # start with half a second
            delay = base * (2 ** (attempt - 1))  # 0.5, 1, 2, 4, ...
            delay += random.uniform(0, 0.25 * delay)  # jitter prevents thundering herd
            delay = min(delay, 10.0)  # cap so we don't wait forever
        self._log(f"waiting {delay:.2f}s before retry")
        time.sleep(delay)

    def _download_one(self, url: str) -> Result:
        """
        Download a single URL with retries and timeouts.
        Steps:
          1) Acquire a token from the rate limiter (may wait).
          2) Make an HTTP GET request with a timeout.
          3) On success: stream bytes to disk in chunks.
          4) On error: decide whether to retry or fail.
        """
        attempts = 0
        last_err = None
        last_status = None

        while attempts <= self.retries:
            attempts += 1
            # Ensure we don't exceed the global requests/sec, This may block until a token is available.
            self._limiter.acquire()

            try:
                headers = {"User-Agent": self.user_agent}
                # Build a GET request; we pass headers like User-Agent
                req = Request(url, headers=headers, method="GET")

                self._log(f"GET {url}")
                # urlopen will raise HTTPError on 4xx/5xx (except some 200-range cases)
                # `timeout` applies to the socket operations.
                with urlopen(req, timeout=self.timeout) as resp:
                    # Some Python versions expose status on resp; otherwise assume 200
                    status = getattr(resp, "status", 200)
                    last_status = status

                    # Convert response headers to a plain dict for easier access
                    hdrs: Dict[str, str] = {k: v for k, v in resp.headers.items()}

                    # Choose a safe filename
                    fname = guess_filename(url, hdrs)
                    out_path = self.output_dir / fname
                    if self.no_clobber:
                        out_path = dedupe_path(out_path)

                    # Stream the response in chunks to avoid loading big files into memory.
                    with open(out_path, "wb") as f:
                        while True:
                            chunk = resp.read(64 * 1024)  # 64 KB
                            if not chunk:
                                break
                            f.write(chunk)

                    # Success!
                    return Result(
                        url=url,
                        ok=True,
                        path=out_path,
                        status=status,
                        attempts=attempts,
                        error=None,
                    )

            except HTTPError as e:
                # HTTPError includes a status code and headers (e.g., Retry-After)
                last_status = e.code
                retry_after = None
                try:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra:
                        retry_after = float(ra)
                except Exception:
                    retry_after = None

                if e.code in RETRIABLE_STATUS and attempts <= self.retries:
                    self._log(f"HTTP {e.code} on {url}; retrying ({attempts}/{self.retries})")
                    self._sleep_backoff(attempts, retry_after)
                    continue

                last_err = f"HTTPError {e.code}: {e.reason}"
                break

            except URLError as e:
                # Network-level error (DNS, connection, TLS, etc.)
                last_err = f"URLError: {e.reason}"
                if attempts <= self.retries:
                    self._log(f"URLError on {url}; retrying ({attempts}/{self.retries})")
                    self._sleep_backoff(attempts, None)
                    continue
                break

            except Exception as e:
                # Catch-all to avoid crashing the whole program on a rare error.
                last_err = f"{type(e).__name__}: {e}"
                if attempts <= self.retries:
                    self._log(f"Error on {url}; retrying ({attempts}/{self.retries})")
                    self._sleep_backoff(attempts, None)
                    continue
                break

        # If we exit the loop, we failed.
        return Result(
            url=url,
            ok=False,
            path=None,
            status=last_status,
            attempts=attempts,
            error=last_err,
        )

    def download_many(self, urls: Iterable[str]) -> List[Result]:
        """
        Input: many URLs (list, tuple, generator — anything iterable)
        Output: list of Result objects

        Download many URLs in parallel using a thread pool.
        We submit a future per URL, then collect results as they complete.

        future is like a recipt that python provides,
          when work is submitted to a thread pool
        """
        futures = [self._pool.submit(self._download_one, u) for u in urls]
        # One thread per URL (up to concurrency), Returns Future objects immediately (submit())
        results: List[Result] = []

        # Key idea: Results arrive as soon as each finishes (Yields each Future the moment it finishes)
        # Faster downloads don’t wait for slower ones (Order depends on completion time, NOT submission order)
        for fut in as_completed(futures):
            results.append(fut.result())
            # If the download is already done → returns immediately
            # If something went wrong → raises the exception from the thread
        return results
        