from rlget.utils import guess_filename, sanitize_filename, dedupe_path
from pathlib import Path

def test_guess_filename_from_headers():
    url = "https://example.com/download"
    headers = {"Content-Disposition": 'attachment; filename="report.pdf"'}
    assert guess_filename(url, headers) == "report.pdf"

def test_guess_filename_from_url():
    url = "https://example.com/files/image.png"
    assert guess_filename(url, {}) == "image.png"

def test_dedupe_path(tmp_path: Path):
    p = tmp_path / "file.txt"
    p.write_text("a")
    p2 = dedupe_path(p)
    assert p2.name.startswith("file(") and p2.suffix == ".txt"