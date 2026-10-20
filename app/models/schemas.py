"""
Pydantic models for all request/response payloads.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class AspectRatio(str, Enum):
    r16x9 = "16:9"
    r9x16 = "9:16"
    r1x1  = "1:1"


class VideoDuration(str, Enum):
    short  = "short"    # ~60 s
    medium = "medium"   # ~120 s
    long   = "long"     # ~180 s


class InputMode(str, Enum):
    pdf    = "pdf"
    script = "script"
    audio  = "audio"


class JobStatus(str, Enum):
    queued    = "queued"
    running   = "running"
    succeeded = "succeeded"
    failed    = "failed"


class VisualStyle(str, Enum):
    cinematic   = "cinematic"
    documentary = "documentary"
    corporate   = "corporate"
    energetic   = "energetic"


# ── PDF ───────────────────────────────────────────────────────────────────────

class PageText(BaseModel):
    page_number: int
    text: str
    headings: List[str] = Field(default_factory=list)


class PDFExtractResponse(BaseModel):
    filename: str
    page_count: int
    pages: List[PageText]
    full_text: str
    ocr_used: bool = False
    ocr_available: bool = False
    warnings: List[str] = Field(default_factory=list)


class PDFScriptRequest(BaseModel):
    full_text: str
    duration: VideoDuration = VideoDuration.medium
    language: str = "en"
    style: VisualStyle = VisualStyle.documentary


class ScriptScene(BaseModel):
    index: int
    text: str
    source_page: Optional[int] = None
    visual_query: str = ""
    duration_hint: float = 0.0   # seconds


class ScriptResponse(BaseModel):
    script_text: str
    scenes: List[ScriptScene]
    word_count: int
    estimated_duration_s: float
    provider: str = "heuristic"


# ── Job ───────────────────────────────────────────────────────────────────────

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    credits_used: float = 0.0
    model: str = "gemini-1.5-flash"
    generation_mode: str = "local"


class VideoSettings(BaseModel):
    duration: VideoDuration = VideoDuration.medium
    language: str = "en"
    voice: str = "default"
    style: VisualStyle = VisualStyle.documentary
    aspect_ratio: AspectRatio = AspectRatio.r16x9
    captions: bool = True
    avoid: List[str] = Field(default_factory=list)
    generation_mode: str = "local"   # "local" | "api"
    api_key: Optional[str] = None


class BRollJobRequest(BaseModel):
    input_mode: InputMode = InputMode.pdf
    script_text: Optional[str] = None      # for script mode
    scenes: Optional[List[ScriptScene]] = None  # optional explicit scenes
    settings: VideoSettings = Field(default_factory=VideoSettings)
    # pdf_path / audio_path are set server-side after upload

    @field_validator("script_text")
    @classmethod
    def script_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("script_text must not be blank")
        return v


class ClipInfo(BaseModel):
    asset_id: str
    provider: str
    source_url: str
    licence_name: str
    licence_url: str
    attribution: str
    relevance_score: float
    selection_reason: str
    is_mock: bool = False
    download_url: Optional[str] = None
    local_path: Optional[str] = None


class SceneResult(BaseModel):
    index: int
    text: str
    start_s: float
    end_s: float
    source_page: Optional[int] = None
    clip: Optional[ClipInfo] = None
    caption_lines: List[str] = Field(default_factory=list)


class JobResult(BaseModel):
    video_url: Optional[str] = None
    captions_url: Optional[str] = None
    timeline_url: Optional[str] = None
    manifest_url: Optional[str] = None
    duration_s: Optional[float] = None
    scenes: List[SceneResult] = Field(default_factory=list)
    aspect_ratio: Optional[str] = None
    generation_mode: str = "local"
    token_usage: Optional[TokenUsage] = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    input_mode: InputMode
    settings: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[JobResult] = None
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"


class ReadyResponse(BaseModel):
    ready: bool
    checks: Dict[str, bool]
