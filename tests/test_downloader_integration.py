import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from rlget.downloader import DownloadManager

class TestHandler(BaseHTTPRequestHandler):
    """
    A tiny local HTTP server used only for tests.
    Endpoints:
      /ok     -> returns a small file with a filename header
      /retry  -> fails twice with 503, then returns 200 "done"
      /rate   -> returns a tiny "R" to help test rate limiting
    """
    counter = 0

    def do_GET(self):
        if self.path == "/ok":
            body = b"hello world" * 100
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header('Content-Disposition', 'attachment; filename="ok.bin"')
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/retry":
            # Fail twice, then succeed. We increment a global counter.
            TestHandler.counter += 1
            if TestHandler.counter < 3:
                self.send_response(503)
                self.end_headers()
            else:
                body = b"done"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        elif self.path == "/rate":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"R")

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default server logging to keep test output clean
        return

def run_server(server):
    server.serve_forever()

def with_server(fn):
    """
    Decorator to start/stop a temporary HTTP server for each test.
    We pick port 0 (OS chooses a free port), and pass host/port to the test.
    """
    def wrapper(tmp_path: Path):
        server = HTTPServer(("127.0.0.1", 0), TestHandler)
        host, port = server.server_address
        t = threading.Thread(target=run_server, args=(server,), daemon=True)
        t.start()
        try:
            fn(tmp_path, host, port)
        finally:
            server.shutdown()
    return wrapper

@with_server
def test_download_ok(tmp_path: Path, host: str, port: int):
    mgr = DownloadManager(output_dir=tmp_path, rate=10, concurrency=2, retries=0, timeout=5)
    try:
        url = f"http://{host}:{port}/ok"
        [res] = mgr.download_many([url])
        assert res.ok and res.path.exists()
    finally:
        mgr.close()

@with_server
def test_download_retry(tmp_path: Path, host: str, port: int):
    TestHandler.counter = 0  # reset between tests
    mgr = DownloadManager(output_dir=tmp_path, rate=10, concurrency=1, retries=3, timeout=5, verbose=True)
    try:
        url = f"http://{host}:{port}/retry"
        [res] = mgr.download_many([url])
        # Should take at least 3 attempts (2 failures + 1 success)
        assert res.ok and res.attempts >= 3
    finally:
        mgr.close()

@with_server
def test_rate_limiting(tmp_path: Path, host: str, port: int):
    mgr = DownloadManager(output_dir=tmp_path, rate=2, concurrency=4, retries=0, timeout=5)
    try:
        urls = [f"http://{host}:{port}/rate" for _ in range(6)]
        start = time.perf_counter()
        results = mgr.download_many(urls)
        elapsed = time.perf_counter() - start

        assert all(r.ok for r in results)
        # 6 requests at 2 req/s ~ 3 seconds (allow tolerance)
        assert elapsed >= 2.0
    finally:
        mgr.close()