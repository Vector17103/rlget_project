from __future__ import annotations
import argparse
from pathlib import Path
from .downloader import DownloadManager

"""
User types command
↓
argparse reads flags
↓
DownloadManager configured
↓
download_many() runs
↓
Results printed
↓
Exit code returned
"""

def build_parser() -> argparse.ArgumentParser:
    """
    Define all the command-line flags. argparse automatically builds --help text.
    """
    p = argparse.ArgumentParser(
        prog="rlget",
        description="Rate-limited CLI downloader (stdlib-only)."
    )
    p.add_argument("URL", nargs="+", help="One or more URLs to download")
    p.add_argument("-o", "--output", default="downloads", help="Output directory (default: downloads)")
    p.add_argument("-r", "--rate", type=float, default=5.0, help="Max requests per second (default: 5)")
    p.add_argument("-c", "--concurrency", type=int, default=4, help="Parallel workers (default: 4)")
    p.add_argument("--retries", type=int, default=3, help="Max retries on retriable errors (default: 3)")
    p.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout seconds (default: 20)")
    p.add_argument("--user-agent", default=None, help="Override User-Agent header")
    p.add_argument("--no-clobber", action="store_true", help="Do not overwrite existing files; add numeric suffix")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    return p

def main(argv: list[str] | None = None) -> int:
    """
    Entry point for both `python -m rlget.cli` and the `rlget` console script (if installed).
    """
    args = build_parser().parse_args(argv)

    mgr = DownloadManager(
        output_dir=Path(args.output),
        rate=args.rate,
        concurrency=args.concurrency,
        retries=args.retries,
        timeout=args.timeout,
        user_agent=args.user_agent,
        no_clobber=args.no_clobber,
        verbose=args.verbose,
    )

    try:
        results = mgr.download_many(args.URL)
    finally:
        # Always close the thread pool
        mgr.close()

    # Print a simple summary and return an appropriate exit code for CI
    ok = 0
    for r in results:
        if r.ok:
            ok += 1
            print(f"OK  {r.url} -> {r.path}")   # OK  https://a.com/file.jpg -> downloads/file.jpg
        else:
            print(f"ERR {r.url} (status={r.status}, attempts={r.attempts}) {r.error}")
            # ERR https://b.com/file.jpg (status=503, attempts=4) HTTPError 503: Service Unavailable
    total = len(results)
    print(f"\nSummary: {ok}/{total} succeeded")
    return 0 if ok == total else 1

if __name__ == "__main__":
    raise SystemExit(main())