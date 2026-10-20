# PDF to Video AI Engine (IncuBrix Assessment 3)

A lightweight, low-cost PDF-to-video web application and background rendering engine. It converts documents, raw narration scripts, and voiceover audio files into finished, licence-clean B-roll videos with synchronized subtitles and complete provenance manifests.

---

## Architecture Overview

```
                                      +------------------------+
                                      |   Browser / REST API   |
                                      +-----------+------------+
                                                  |
                  +-------------------------------+-------------------------------+
                  |                               |                               |
       [POST /api/v1/pdf/extract]       [POST /api/v1/pdf/script]       [POST /api/v1/broll/jobs]
                  |                               |                               |
                  v                               v                               v
          +---------------+              +-----------------+             +-----------------+
          | PDF Extractor |              | Script Heuristic|             | SQLite Job Store|
          | (PyMuPDF/pypdf)              | (TF Keyword Gen)|             |   (WAL Mode)    |
          +---------------+              +-----------------+             +--------+--------+
                                                                                  |
                                                                        +---------v---------+
                                                                        | Background Worker |
                                                                        | (ThreadPool/Async)|
                                                                        +----+----+----+----+
                                                                             |    |    |
                               +---------------------------------------------+    |    +--------------------+
                               |                                                  |                         |
                               v                                                  v                         v
                       +---------------+                                  +---------------+         +---------------+
                       |  TTS Adapter  |                                  | Footage Search|         | FFmpeg Engine |
                       | (gTTS / Edge) |                                  | (Pexels / Mock|         | H.264/AAC Mux |
                       +-------+-------+                                  +-------+-------+         +-------+-------+
                               |                                                  |                         |
                               +--------------------------+-----------------------+                         |
                                                          |                                                 |
                                                          v                                                 v
                                                +--------------------+                            +-------------------+
                                                | Timeline & Captions|                            |   MP4 + SRT +     |
                                                |   Generator        +--------------------------->| timeline.json +   |
                                                +--------------------+                            | manifest.json     |
                                                                                                  +-------------------+
```

---

## Key Features

1. **Multi-Mode Input**:
   - **PDF Upload**: Extracts text with page annotations and structure; optional Tesseract OCR for scanned pages.
   - **Direct Script Input**: Multi-scene custom script editor.
   - **Audio File Upload**: MP3, WAV, M4A with audio duration timing and optional transcription.
2. **Honest, Deterministic Script Generation**:
   - Uses heuristic term-frequency (TF) sentence scoring and keyword extraction.
   - Preserves source page numbers and logical scene breaks.
   - Explicitly reports provider as `"heuristic"` in the manifest without falsely claiming generative LLM intelligence.
3. **Licence-Clean Footage & Provenance**:
   - Pexels API integration with query expansion and visual style modifiers (`cinematic`, `documentary`, `corporate`, `energetic`).
   - Strict de-duplication: no clip is repeated within a video.
   - Complete rights metadata: asset ID, photographer attribution, licence URL, relevance score, and selection reason recorded per scene.
   - Deterministic offline mock provider with clear mock warnings for automated testing.
4. **Dual Generation Modes (Local vs. AI Animated Engine)**:
   - **Local Engine (Default)**: Instant stock B-roll retrieval and offline card pipeline with zero API token cost.
   - **AI Animated Engine (Gemini Omni Flash)**: Thematically animated 30 fps video generation per narration beat (botanical/flower blooming, robotics HUD, cybernetic tech grids, neural synapse networks) with real-time token tracking and credit accounting. Full documentation in [AI_ANIMATED_VIDEO_GENERATION.md](file:///D:/VideoEngine/AI_ANIMATED_VIDEO_GENERATION.md).
5. **FFmpeg Video Rendering**:
   - Standard 1080p output at 30 fps in 16:9, 9:16, or 1:1 aspect ratios.
   - Burned-in subtitles option and standalone `captions.srt`.
   - Normalised video segments with zero audio drift.
5. **IncuBrix Integration Standard Compliance**:
   - Asynchronous job execution returning HTTP 202 with polling endpoint `GET /api/v1/jobs/{job_id}`.
   - `Idempotency-Key` header support to prevent duplicate renders on retry.
   - Standardized JSON errors: `{"error": {"code", "message", "retryable", "details"}}`.
   - Health (`/health`) and readiness (`/ready`) probes.
   - Batch runner CLI (`batch_runner.py`) for automated folder evaluation.

---

## Quickstart (Under 10 Commands)

### Local Development (Python 3.11+)

```bash
# 1. Clone or enter directory
cd d:/VideoEngine

# 2. Create and activate virtual environment (optional)
python -m venv venv
./venv/Scripts/activate

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. Run test fixtures generator
python fixtures/make_fixtures.py

# 6. Run test suite (55 automated tests)
pytest tests/ -v

# 7. Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your web browser.

---

## Docker Deployment

To launch the entire stack in an isolated container with FFmpeg and Tesseract pre-installed:

```bash
docker compose up --build -d
```

Check health:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

---

## Configuration Settings (`.env`)

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server bind port |
| `FOOTAGE_PROVIDER` | `mock` | `pexels` or `mock` |
| `PEXELS_API_KEY` | *(None)* | API key from [pexels.com/api](https://www.pexels.com/api/) |
| `TTS_PROVIDER` | `gtts` | `gtts`, `edge`, `espeak`, or `mock` |
| `EDGE_TTS_VOICE` | `en-US-AriaNeural` | Voice ID when using Edge TTS |
| `TRANSCRIPTION_PROVIDER` | `mock` | `whisper` or `mock` |
| `FFMPEG_BIN` | `ffmpeg` | Path or binary name for FFmpeg |
| `FFPROBE_BIN` | `ffprobe` | Path or binary name for FFprobe |
| `MAX_CONCURRENT_JOBS` | `10` | Maximum jobs processing simultaneously |
| `MAX_PDF_SIZE_MB` | `50` | Maximum allowed PDF size |
| `MAX_PDF_PAGES` | `200` | Maximum allowed PDF page count |
| `MAX_AUDIO_SIZE_MB` | `100` | Maximum allowed audio upload size |

---

## Error Codes Reference

All API error responses follow the standard IncuBrix error schema:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "retryable": false,
    "details": null
  }
}
```

| Error Code | HTTP Status | Retryable | Description |
|---|---|---|---|
| `BAD_REQUEST` | 400 | No | Malformed request syntax or parameters |
| `NOT_FOUND` | 404 | No | Job ID or requested resource not found |
| `PAYLOAD_TOO_LARGE` | 413 | No | File exceeds size limit (50MB PDF / 100MB Audio) |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | No | File is not an accepted PDF or audio format |
| `VALIDATION_ERROR` | 422 | No | Missing required fields, invalid enum, or corrupted file |
| `CAPACITY_EXCEEDED` | 429 | Yes | Server reached maximum concurrent jobs |
| `INTERNAL_ERROR` | 500 | Yes | Unexpected backend processing error |
| `SERVICE_UNAVAILABLE` | 503 | Yes | External provider or dependency unreachable |

---

## Batch Runner Usage

Execute automated test runs against a folder of PDFs, scripts, or audio files:

```bash
# Run against test fixtures
python batch_runner.py --input-dir fixtures/ --output-dir batch_results/ --aspect-ratio 16:9

# Run a single file
python batch_runner.py --input-file fixtures/sample.pdf --output-dir batch_results/
```

Results are saved to `batch_results/` including:
- `batch_summary.json` (per-file latency, status, warnings, and artifact paths)
- Downloaded `video_*.mp4`, `captions.srt`, `timeline.json`, and `manifest.json`

---

## Troubleshooting

1. **FFmpeg missing**:
   - Install FFmpeg via your system package manager (`apt-get install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` on macOS, or download Windows builds from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)).
   - Set `FFMPEG_BIN` and `FFPROBE_BIN` in `.env` to the binary paths.
2. **PyMuPDF DLL loading issues on Windows**:
   - The application automatically falls back to pure-Python `pypdf` if PyMuPDF's C runtime is missing.
3. **Pexels API Key**:
   - If `FOOTAGE_PROVIDER=pexels` is specified without an API key, jobs return a clear warning and fall back to local rendering.
