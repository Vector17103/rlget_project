# rlget — Rate‑Limited CLI Downloader (Stdlib‑Only)

This is a beginner-friendly command-line tool that downloads one or more URLs carefully:
- Global **rate limit** (X requests per second)
- **Concurrency** (several downloads at once)
- **Retries** with exponential backoff (and respects Retry-After)
- Per-request **timeouts**
- Safe filenames derived from headers or URLs
- `--no-clobber` avoids overwriting existing files

## Quick start

Run directly (no install required):
```bash
python -m rlget.cli https://example.com -o downloads -r 2 -c 2 --retries 2 --timeout 10