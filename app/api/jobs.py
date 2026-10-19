"""
Job creation and status API endpoints.

POST /api/v1/broll/jobs  - Create a new video generation job (202 Accepted)
GET  /api/v1/jobs/{job_id} - Poll job status

Supports Idempotency-Key header for safe retries.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.database import (
    count_running_jobs,
    create_job,
    get_job,
    get_job_by_idempotency_key,
    init_db,
    update_job,
)
from app.core.security import safe_filename, validate_audio_signature, validate_pdf_signature
from app.models.schemas import (
    AspectRatio,
    BRollJobRequest,
    InputMode,
    JobResponse,
    JobResult,
    JobStatus,
    ScriptScene,
    VideoSettings,
    VisualStyle,
    VideoDuration,
)
from app.services.job_runner import run_job
from app.services.pdf_extractor import extract_pdf
from app.services.script_generator import generate_script, scenes_from_script
from app.services.transcription_adapter import get_transcription_adapter

router = APIRouter(tags=["jobs"])

# Shared thread pool for background jobs (max 1 worker for 512MB RAM stability)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-worker")


def _job_to_response(job: dict) -> JobResponse:
    """Convert a raw DB row dict to a JobResponse model."""
    result_data = job.get("result")
    result = None
    if result_data and isinstance(result_data, dict):
        try:
            result = JobResult(**result_data)
        except Exception:
            pass

    return JobResponse(
        job_id=job["id"],
        status=JobStatus(job["status"]),
        progress=job.get("progress", 0),
        input_mode=InputMode(job.get("input_mode", "pdf")),
        settings=job.get("settings", {}),
        result=result,
        error=job.get("error"),
        warnings=job.get("warnings", []),
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
    )


def _submit_job(
    job_id: str,
    scenes: list,
    settings: VideoSettings,
    db_path: Path,
    output_dir: Path,
    cfg,
    audio_path: Optional[Path] = None,
):
    """Background task: run the job pipeline and update DB on completion."""
    update_job(db_path, job_id, status="running", started_at=time.time())
    try:
        result = run_job(
            job_id=job_id,
            scenes=scenes,
            settings=settings,
            output_dir=output_dir,
            db_path=db_path,
            cfg=cfg,
            audio_path=audio_path,
        )
        update_job(
            db_path, job_id,
            status="succeeded",
            progress=100,
            result=result.model_dump(),
            finished_at=time.time(),
        )
    except Exception as exc:
        update_job(
            db_path, job_id,
            status="failed",
            error=str(exc)[:2000],
            finished_at=time.time(),
        )


# ── POST /api/v1/broll/jobs ───────────────────────────────────────────────────

@router.post(
    "/api/v1/broll/jobs",
    status_code=202,
    response_model=JobResponse,
    summary="Create a B-roll video generation job",
)
async def create_broll_job(
    # Common fields
    input_mode: str = Form("pdf", description="pdf | script | audio"),
    script_text: Optional[str] = Form(None),
    duration: str = Form("medium"),
    language: str = Form("en"),
    voice: str = Form("default"),
    style: str = Form("documentary"),
    aspect_ratio: str = Form("16:9"),
    captions: bool = Form(True),
    avoid: str = Form("", description="Comma-separated terms to avoid in footage"),
    # File uploads
    pdf_file: Optional[UploadFile] = File(None),
    audio_file: Optional[UploadFile] = File(None),
    # Idempotency
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cfg = get_settings()
    db_path = cfg.DB_PATH
    init_db(db_path)

    # ── Idempotency check ────────────────────────────────────────────────────
    if idempotency_key:
        existing = get_job_by_idempotency_key(db_path, idempotency_key)
        if existing:
            return _job_to_response(existing)

    # ── Validate enums ───────────────────────────────────────────────────────
    try:
        _input_mode = InputMode(input_mode)
        _duration   = VideoDuration(duration)
        _style      = VisualStyle(style)
        _ar         = AspectRatio(aspect_ratio)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    job_id = str(uuid.uuid4())
    audio_path_for_job: Optional[Path] = None

    # ── Input processing & validation ─────────────────────────────────────────
    if _input_mode == InputMode.pdf:
        if pdf_file is None:
            raise HTTPException(status_code=422, detail="A PDF file is required for input_mode=pdf.")

        data = await pdf_file.read()
        max_bytes = cfg.MAX_PDF_SIZE_MB * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds {cfg.MAX_PDF_SIZE_MB} MB limit.",
            )
        try:
            validate_pdf_signature(data)
            extracted = extract_pdf(data, filename=safe_filename(pdf_file.filename or "upload.pdf"),
                                    max_pages=cfg.MAX_PDF_PAGES)
            script_result = generate_script(extracted.full_text, duration=_duration, style=_style)
            scenes = script_result.scenes
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    elif _input_mode == InputMode.script:
        if not script_text or not script_text.strip():
            raise HTTPException(status_code=422, detail="script_text is required for input_mode=script.")
        scenes = scenes_from_script(script_text, style=_style)

    elif _input_mode == InputMode.audio:
        if audio_file is None:
            raise HTTPException(status_code=422, detail="An audio file is required for input_mode=audio.")

        audio_data = await audio_file.read()
        max_bytes = cfg.MAX_AUDIO_SIZE_MB * 1024 * 1024
        if len(audio_data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio exceeds {cfg.MAX_AUDIO_SIZE_MB} MB limit.",
            )
        try:
            validate_audio_signature(audio_data, audio_file.filename or "audio.mp3")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        # Save audio file
        safe_name = safe_filename(audio_file.filename or "audio.mp3")
        audio_save_path = cfg.UPLOAD_DIR / f"{job_id}_{safe_name}"
        audio_save_path.write_bytes(audio_data)
        audio_path_for_job = audio_save_path

        # Transcribe to get scenes
        transcriber = get_transcription_adapter(cfg.TRANSCRIPTION_PROVIDER)
        transcript = transcriber.transcribe(audio_save_path, language=language)
        scenes = scenes_from_script(transcript, style=_style)

    else:
        raise HTTPException(status_code=422, detail=f"Unknown input_mode: {_input_mode}")

    if not scenes:
        raise HTTPException(status_code=422, detail="No scenes could be generated from the provided input.")

    # ── Concurrency check ────────────────────────────────────────────────────
    running = count_running_jobs(db_path)
    if running >= cfg.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Server is at capacity ({cfg.MAX_CONCURRENT_JOBS} concurrent jobs). Try again shortly.",
        )

    settings = VideoSettings(
        duration=_duration,
        language=language,
        voice=voice,
        style=_style,
        aspect_ratio=_ar,
        captions=captions,
        avoid=[a.strip() for a in avoid.split(",") if a.strip()],
    )

    # ── Create job record ────────────────────────────────────────────────────
    create_job(
        db_path,
        job_id=job_id,
        idempotency_key=idempotency_key,
        input_mode=_input_mode.value,
        settings=settings.model_dump(),
    )

    # ── Submit background job ────────────────────────────────────────────────
    _executor.submit(
        _submit_job,
        job_id,
        scenes,
        settings,
        db_path,
        cfg.OUTPUT_DIR,
        cfg,
        audio_path_for_job,
    )

    job = get_job(db_path, job_id)
    return _job_to_response(job)


# ── GET /api/v1/jobs/{job_id} ─────────────────────────────────────────────────

@router.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobResponse,
    summary="Poll job status",
)
async def get_job_status(job_id: str):
    cfg = get_settings()
    db_path = cfg.DB_PATH
    init_db(db_path)

    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return _job_to_response(job)
