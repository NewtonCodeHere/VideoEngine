"""
Application configuration loaded from environment variables / .env file.
All secrets must be set as environment variables – never hardcoded.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "info"

    # ── Paths ─────────────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "outputs"
    DB_PATH: Path = BASE_DIR / "jobs.db"
    FIXTURE_DIR: Path = BASE_DIR / "fixtures"

    # ── Limits ────────────────────────────────────────────────────────────────
    MAX_PDF_SIZE_MB: int = 50
    MAX_PDF_PAGES: int = 200
    MAX_AUDIO_SIZE_MB: int = 100
    MAX_CONCURRENT_JOBS: int = 10
    JOB_TIMEOUT_SECONDS: int = 600

    # ── Footage Provider ──────────────────────────────────────────────────────
    FOOTAGE_PROVIDER: str = "pexels"          # pexels | mock
    PEXELS_API_KEY: Optional[str] = None
    FOOTAGE_MAX_CLIPS_PER_JOB: int = 20
    FOOTAGE_MIN_RELEVANCE: float = 0.25

    # ── TTS Adapter ───────────────────────────────────────────────────────────
    TTS_PROVIDER: str = "gtts"               # gtts | espeak | edge | mock
    TTS_LANGUAGE: str = "en"
    TTS_VOICE: str = "default"
    EDGE_TTS_VOICE: str = "en-US-AriaNeural"

    # ── Transcription ─────────────────────────────────────────────────────────
    TRANSCRIPTION_PROVIDER: str = "mock"     # whisper | mock

    # ── FFmpeg ────────────────────────────────────────────────────────────────
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    VIDEO_FPS: int = 30
    VIDEO_WIDTH: int = 1920
    VIDEO_HEIGHT: int = 1080
    VIDEO_CRF: int = 23
    VIDEO_PRESET: str = "fast"
    AUDIO_BITRATE: str = "128k"
    VIDEO_BITRATE: str = "2000k"

    # ── Script Generation ─────────────────────────────────────────────────────
    SCRIPT_PROVIDER: str = "heuristic"       # heuristic | openai (not used)

    # ── Security ──────────────────────────────────────────────────────────────
    ALLOWED_HOSTS: str = "*"
    MAX_REQUEST_SIZE_MB: int = 150


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    # Ensure directories exist
    s.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    s.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    s.FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    return s
