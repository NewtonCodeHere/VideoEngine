"""
PDF extraction and script generation API endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.security import safe_filename, validate_pdf_signature
from app.models.schemas import (
    PDFExtractResponse,
    PDFScriptRequest,
    ScriptResponse,
    VideoDuration,
    VisualStyle,
)
from app.services.pdf_extractor import extract_pdf
from app.services.script_generator import generate_script

router = APIRouter(prefix="/api/v1/pdf", tags=["pdf"])


@router.post("/extract", response_model=PDFExtractResponse, summary="Extract text from a PDF")
async def extract_pdf_endpoint(
    file: UploadFile = File(..., description="PDF file to extract text from"),
    use_ocr: bool = Form(False, description="Enable OCR for scanned pages (requires Tesseract)"),
):
    """
    Upload a PDF and extract its text content page by page.

    - Validates file type (MIME + magic bytes)
    - Rejects encrypted, corrupted, empty, or oversized PDFs
    - Returns per-page text with headings and page numbers
    - Reports OCR availability
    """
    cfg = get_settings()

    # MIME check
    if file.content_type not in ("application/pdf", "application/octet-stream", None):
        # Be lenient with content type since browsers differ
        if file.content_type and not file.content_type.endswith("pdf"):
            raise HTTPException(
                status_code=415,
                detail="Only PDF files are accepted.",
            )

    data = await file.read()

    # Size check
    max_bytes = cfg.MAX_PDF_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum size of {cfg.MAX_PDF_SIZE_MB} MB.",
        )

    # Signature check
    try:
        validate_pdf_signature(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    filename = safe_filename(file.filename or "upload.pdf")

    try:
        result = extract_pdf(
            data,
            filename=filename,
            max_pages=cfg.MAX_PDF_PAGES,
            use_ocr=use_ocr,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return result


@router.post("/script", response_model=ScriptResponse, summary="Generate a narration script from PDF text")
async def generate_script_endpoint(body: PDFScriptRequest):
    """
    Generate a narration script from previously extracted PDF text.

    Uses a heuristic TF-IDF method – no AI/LLM is involved.
    The response explicitly states provider='heuristic'.
    """
    if not body.full_text.strip():
        raise HTTPException(status_code=422, detail="full_text must not be empty.")

    try:
        result = generate_script(
            body.full_text,
            duration=body.duration,
            language=body.language,
            style=body.style,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return result
