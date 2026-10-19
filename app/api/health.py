"""
Health check and readiness probe endpoints.
"""
from __future__ import annotations

import shutil

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import init_db
from app.models.schemas import HealthResponse, ReadyResponse
from app.services.video_renderer import check_ffmpeg

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health():
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
async def ready():
    cfg = get_settings()
    checks = {}

    # DB writeable
    try:
        init_db(cfg.DB_PATH)
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # Upload dir writable
    try:
        cfg.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        test_file = cfg.UPLOAD_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["upload_dir"] = True
    except Exception:
        checks["upload_dir"] = False

    # Output dir writable
    try:
        cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        test_file = cfg.OUTPUT_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["output_dir"] = True
    except Exception:
        checks["output_dir"] = False

    # FFmpeg available
    ffmpeg_ok, _ = check_ffmpeg(cfg.FFMPEG_BIN, cfg.FFPROBE_BIN)
    checks["ffmpeg"] = ffmpeg_ok

    # PyMuPDF or pypdf available
    pdf_ok = False
    try:
        import fitz
        _doc = fitz.open()
        _doc.close()
        checks["pymupdf"] = True
        pdf_ok = True
    except Exception:
        checks["pymupdf"] = False

    try:
        import pypdf
        checks["pypdf"] = True
        pdf_ok = True
    except ImportError:
        checks["pypdf"] = False
    checks["pdf_parser"] = pdf_ok

    # Tesseract (optional)
    try:
        import pytesseract
        checks["tesseract_ocr"] = True
    except ImportError:
        checks["tesseract_ocr"] = False

    return ReadyResponse(
        ready=all(v for k, v in checks.items() if k in ("database", "upload_dir", "output_dir", "pdf_parser")),
        checks=checks,
    )
