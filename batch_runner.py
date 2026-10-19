"""
Batch runner CLI tool for testing multiple inputs against the VideoEngine API.
Satisfies Integration Standard Point 10.

Usage:
    python batch_runner.py --input-dir fixtures/ --output-dir batch_results/ --api-url http://localhost:8000
    python batch_runner.py --input-file fixtures/sample.pdf --output-dir batch_results/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx


def submit_pdf_job(api_url: str, pdf_path: Path, settings: Dict[str, Any]) -> str:
    """Submit a PDF file to the jobs endpoint and return job_id."""
    with open(pdf_path, "rb") as f:
        files = {"pdf_file": (pdf_path.name, f, "application/pdf")}
        data = {
            "input_mode": "pdf",
            "duration": settings.get("duration", "short"),
            "language": settings.get("language", "en"),
            "voice": settings.get("voice", "default"),
            "style": settings.get("style", "documentary"),
            "aspect_ratio": settings.get("aspect_ratio", "16:9"),
            "captions": str(settings.get("captions", True)).lower(),
        }
        resp = httpx.post(f"{api_url}/api/v1/broll/jobs", data=data, files=files, timeout=60.0)
        resp.raise_for_status()
        return resp.json()["job_id"]


def submit_text_job(api_url: str, text: str, name: str, settings: Dict[str, Any]) -> str:
    """Submit a script text to the jobs endpoint and return job_id."""
    data = {
        "input_mode": "script",
        "script_text": text,
        "duration": settings.get("duration", "short"),
        "language": settings.get("language", "en"),
        "voice": settings.get("voice", "default"),
        "style": settings.get("style", "documentary"),
        "aspect_ratio": settings.get("aspect_ratio", "16:9"),
        "captions": str(settings.get("captions", True)).lower(),
    }
    resp = httpx.post(f"{api_url}/api/v1/broll/jobs", data=data, timeout=30.0)
    resp.raise_for_status()
    return resp.json()["job_id"]


def poll_job(api_url: str, job_id: str, timeout: int = 300) -> Dict[str, Any]:
    """Poll job status until completed or timed out."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        resp = httpx.get(f"{api_url}/api/v1/jobs/{job_id}", timeout=10.0)
        resp.raise_for_status()
        job = resp.json()
        status = job.get("status")
        if status in ("succeeded", "failed"):
            return job
        time.sleep(1.5)
    raise TimeoutError(f"Job {job_id} exceeded poll timeout of {timeout}s")


def download_outputs(api_url: str, job_result: Dict[str, Any], target_dir: Path) -> Dict[str, str]:
    """Download result files to the target directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = {}
    result = job_result.get("result") or {}
    
    for key in ("video_url", "captions_url", "timeline_url", "manifest_url"):
        url_path = result.get(key)
        if url_path:
            filename = Path(url_path).name
            out_file = target_dir / filename
            full_url = f"{api_url.rstrip('/')}{url_path}"
            try:
                r = httpx.get(full_url, timeout=30.0)
                if r.status_code == 200:
                    out_file.write_bytes(r.content)
                    saved_paths[key] = str(out_file)
            except Exception as e:
                print(f"Warning: could not download {full_url}: {e}", file=sys.stderr)
    return saved_paths


def run_batch(input_paths: List[Path], output_dir: Path, api_url: str, settings: Dict[str, Any]):
    """Execute a batch of inputs and generate batch_summary.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_report: List[Dict[str, Any]] = []

    print(f"Starting batch runner with {len(input_paths)} item(s) targeting {api_url}...")

    for path in input_paths:
        print(f"\nProcessing {path.name}...")
        item_summary = {
            "input_file": str(path),
            "filename": path.name,
            "status": "pending",
            "start_time": time.time(),
        }

        try:
            if path.suffix.lower() == ".pdf":
                job_id = submit_pdf_job(api_url, path, settings)
            elif path.suffix.lower() in (".txt", ".md"):
                text = path.read_text(encoding="utf-8")
                job_id = submit_text_job(api_url, text, path.name, settings)
            elif path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                text = data.get("script") or data.get("text") or ""
                job_id = submit_text_job(api_url, text, path.name, settings)
            else:
                print(f"Skipping unsupported file type: {path.name}")
                continue

            item_summary["job_id"] = job_id
            print(f"  Job submitted: {job_id}. Polling...")

            job_data = poll_job(api_url, job_id)
            item_summary["status"] = job_data.get("status")
            item_summary["error"] = job_data.get("error")
            item_summary["warnings"] = job_data.get("warnings", [])
            item_summary["elapsed_s"] = round(time.time() - item_summary["start_time"], 2)

            # Download artifacts
            item_out_dir = output_dir / f"job_{job_id[:8]}_{path.stem}"
            saved = download_outputs(api_url, job_data, item_out_dir)
            item_summary["saved_files"] = saved

            print(f"  Result: {job_data.get('status')} in {item_summary['elapsed_s']}s")

        except Exception as exc:
            item_summary["status"] = "failed"
            item_summary["error"] = str(exc)
            item_summary["elapsed_s"] = round(time.time() - item_summary["start_time"], 2)
            print(f"  Error: {exc}")

        summary_report.append(item_summary)

    # Write summary
    summary_path = output_dir / "batch_summary.json"
    summary_path.write_text(json.dumps(summary_report, indent=2), encoding="utf-8")
    print(f"\nBatch completed. Summary saved to {summary_path}")


def main():
    parser = argparse.ArgumentParser(description="VideoEngine Batch Runner")
    parser.add_argument("--input-dir", "-i", type=str, help="Directory containing test files (.pdf, .txt, .json)")
    parser.add_argument("--input-file", "-f", type=str, help="Single test file to process")
    parser.add_argument("--output-dir", "-o", type=str, default="batch_results", help="Directory to save outputs")
    parser.add_argument("--api-url", "-u", type=str, default="http://localhost:8000", help="Base URL of VideoEngine API")
    parser.add_argument("--aspect-ratio", type=str, default="16:9", choices=["16:9", "9:16", "1:1"])
    parser.add_argument("--duration", type=str, default="short", choices=["short", "medium", "long"])
    args = parser.parse_args()

    paths: List[Path] = []
    if args.input_file:
        p = Path(args.input_file)
        if p.exists():
            paths.append(p)
    elif args.input_dir:
        d = Path(args.input_dir)
        if d.is_dir():
            for ext in ("*.pdf", "*.txt", "*.json"):
                paths.extend(d.glob(ext))
    else:
        # Default to fixtures dir
        default_dir = Path(__file__).parent / "fixtures"
        if default_dir.is_dir():
            for ext in ("*.pdf", "*.txt"):
                paths.extend(default_dir.glob(ext))

    if not paths:
        print("No input files found to process.", file=sys.stderr)
        sys.exit(1)

    settings = {
        "aspect_ratio": args.aspect_ratio,
        "duration": args.duration,
    }
    run_batch(paths, Path(args.output_dir), args.api_url, settings)


if __name__ == "__main__":
    main()
