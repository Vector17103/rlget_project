from __future__ import annotations
import os
import re
from urllib.parse import urlparse, unquote
from pathlib import Path
from typing import Mapping, Optional

# This regex tries to extract a filename from a Content-Disposition header.
# It supports patterns like:
#   Content-Disposition: attachment; filename="report.pdf" - Classic format
#   Content-Disposition: attachment; filename*=UTF-8''photo%20(1).jpg - RFC 5987 format
#
# We capture either the RFC 5987 filename* form or the regular filename= form.
_filename_re = re.compile(
    r"filename\*=.*''([^;]+)|filename=\"?([^\";]+)\"?",
    re.IGNORECASE
)

def guess_filename(url: str, headers: Optional[Mapping[str, str]] = None, default: str = "download") -> str:
    """
    Decide what to name the file we download.
    Priority:
      1) If server provides Content-Disposition filename, use that
      2) Otherwise, use the last piece of the URL path
      3) Otherwise, fall back to 'default'
    """
    # 1) Check Content-Disposition header if present
    if headers:
        cd = headers.get('Content-Disposition') or headers.get('content-disposition')
        if cd:
            m = _filename_re.search(cd)
            if m:
                # group(1) is from filename*, group(2) is from filename=
                candidate = m.group(1) or m.group(2)
                if candidate:
                    return sanitize_filename(unquote(candidate))
                # unquote() coverts URL encoding
                # sanitize_filename() makes it safe for OS

    # 2) Derive from URL path (e.g., /files/image.png -> image.png)
    path = urlparse(url).path
    name = os.path.basename(path)
    # URL: https://example.com/files/image.png
    # path: /files/image.png
    # basename: image.png
    if not name:
        # 3) Fall back
        return default
    return sanitize_filename(unquote(name))

def sanitize_filename(name: str) -> str:
    """
    Make the filename safe across OSes by removing illegal characters.
    - On Windows, characters like \ / : * ? " < > | are not allowed.
    - We'll replace them with underscore.
    """
    name = name.strip().replace("\n", " ").replace("\r", " ")
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name or "download" # If everything got stripped → return "download".

def dedupe_path(path: Path) -> Path:
    """
    If 'path' already exists, append (1), (2), ... to avoid overwriting.
    Example:
      if "photo.jpg" exists, we try "photo(1).jpg", then "photo(2).jpg", etc.
    """
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    # parent = directory containing the file, eg: downloads
    # photo.jpg, stem → photo, suffix → .jpg
    i = 1
    while True:
        candidate = parent / f"{stem}({i}){suffix}" # → Path("downloads/photo(1).jpg")
        if not candidate.exists(): # Stops as soon as it finds a free name.
            return candidate
        i += 1