"""
Security and file validation utilities.
"""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional

SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._\-]")


def safe_filename(name: str, max_len: int = 128) -> str:
    """Return a path-safe version of a filename."""
    # Remove directory components
    name = Path(name).name
    name = SAFE_FILENAME_RE.sub("_", name)
    return name[:max_len] or "upload"


def validate_pdf_signature(data: bytes) -> None:
    """Raise ValueError if data does not start with %PDF- magic bytes."""
    if not data[:5].startswith(b"%PDF-"):
        raise ValueError(
            "The uploaded file is not a valid PDF "
            "(missing %PDF- header signature)."
        )


def validate_audio_signature(data: bytes, filename: str) -> None:
    """Basic MIME sniffing for audio files (MP3, WAV, M4A)."""
    ext = Path(filename).suffix.lower()
    if ext not in {".mp3", ".wav", ".m4a", ".ogg"}:
        raise ValueError(
            f"Unsupported audio format '{ext}'. "
            "Accepted formats: MP3, WAV, M4A."
        )
    # Check magic bytes
    if ext == ".wav" and not data[:4] == b"RIFF":
        raise ValueError("WAV file has invalid header (expected RIFF).")
    if ext == ".mp3" and not (data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3")):
        raise ValueError("MP3 file has invalid header.")


def validate_url_safe(url: str) -> str:
    """
    Validate that a URL is http/https and not a private/internal address.
    Protects against SSRF attacks when fetching user-supplied URLs.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme}")

    host = parsed.hostname or ""
    # Block private/loopback ranges
    _blocked = [
        "localhost", "127.", "10.", "172.16.", "172.17.", "172.18.",
        "172.19.", "172.2", "172.3", "192.168.", "169.254.", "::1",
        "0.0.0.0",
    ]
    for blocked in _blocked:
        if host.startswith(blocked) or host == blocked.rstrip("."):
            raise ValueError(f"URL host '{host}' is not allowed (private address).")

    return url


def file_hash(data: bytes, algo: str = "sha256") -> str:
    """Return hex digest of file content."""
    h = hashlib.new(algo)
    h.update(data)
    return h.hexdigest()
