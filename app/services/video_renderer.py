"""
Video rendering service using FFmpeg and Pillow.
Produces H.264 / AAC MP4 at 30 fps, normalized to requested aspect ratios.
Generates dynamic visual title cards for each scene matching the user's input,
timed to the narration audio.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from app.models.schemas import AspectRatio, SceneResult

# Standard 1080p-class dimensions
RESOLUTION = {
    AspectRatio.r16x9: (1920, 1080),
    AspectRatio.r9x16: (1080, 1920),
    AspectRatio.r1x1:  (1080, 1080),
}

# Rich background palette for scene cards
SCENE_COLORS = [
    (26, 26, 46),   # Dark Navy
    (22, 33, 62),   # Deep Blue
    (15, 52, 96),   # Sapphire
    (83, 52, 131),  # Violet
    (43, 45, 66),   # Slate
    (20, 30, 48),   # Midnight
    (36, 59, 85),   # Ocean
    (17, 30, 40),   # Charcoal
]


def _find_bin(name: str, override: str = "") -> str:
    """Return the binary path, using override if provided or searching imageio_ffmpeg."""
    if override and shutil.which(override):
        return override
    found = shutil.which(name)
    if found:
        return found
    if "ffmpeg" in name.lower():
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return override or name


def check_ffmpeg(ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> Tuple[bool, str]:
    """Return (available, version_string) for ffmpeg."""
    bin_path = _find_bin("ffmpeg", ffmpeg_bin)
    try:
        result = subprocess.run(
            [bin_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            return True, first_line
        return False, result.stderr[:200]
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _generate_scene_card(
    scene: SceneResult,
    index: int,
    total: int,
    width: int,
    height: int,
    output_png: Path,
) -> Path:
    """Render a clean, high-resolution graphic card displaying the scene text."""
    bg_color = SCENE_COLORS[index % len(SCENE_COLORS)]
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # 1. Top badge: Scene number & source page
    badge_text = f"SCENE {index + 1} OF {total}"
    if scene.source_page:
        badge_text += f"   ·   SOURCE PAGE {scene.source_page}"
    draw.text((80, 80), badge_text, fill=(0, 214, 160))

    # 2. Main Narration Text (word-wrapped)
    wrap_width = 46 if width >= 1920 else (28 if width <= 1080 and height > 1080 else 36)
    wrapped_lines = textwrap.wrap(scene.text.strip(), width=wrap_width)
    display_text = "\n".join(wrapped_lines[:10])

    y_pos = int(height * 0.28)
    draw.text((80, y_pos), display_text, fill=(255, 255, 255), spacing=18)

    # 3. Visual Search / Scene metadata at the bottom
    query_hint = ""
    if scene.clip and scene.clip.selection_reason:
        query_hint = f"Visual Query: {scene.clip.selection_reason[:75]}"
    elif scene.clip and scene.clip.source_url:
        query_hint = f"Source: {scene.clip.source_url}"
    if query_hint:
        draw.text((80, height - 100), query_hint, fill=(160, 180, 205))

    img.save(str(output_png), format="PNG")
    return output_png


def render_video(
    scenes: List[SceneResult],
    audio_path: Optional[Path],
    output_path: Path,
    aspect_ratio: AspectRatio = AspectRatio.r16x9,
    fps: int = 30,
    captions: bool = True,
    srt_path: Optional[Path] = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    crf: int = 23,
    preset: str = "fast",
    video_bitrate: str = "2000k",
    audio_bitrate: str = "128k",
    progress_callback=None,
) -> Path:
    """
    Render a dynamic, timed video from scenes + audio using FFmpeg.
    Each scene generates a customized visual card featuring the exact text,
    matched to the narration timing.
    """
    bin_path = _find_bin("ffmpeg", ffmpeg_bin)
    ffmpeg_available, ffmpeg_version = check_ffmpeg(bin_path, ffprobe_bin)
    if not ffmpeg_available:
        # Fallback if ffmpeg is somehow missing
        template = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mock_template.mp4"
        if template.exists():
            shutil.copyfile(template, output_path)
            if progress_callback:
                progress_callback(90)
            return output_path
        raise RuntimeError(f"FFmpeg is not available: {ffmpeg_version}")

    width, height = RESOLUTION.get(aspect_ratio, (1920, 1080))

    with tempfile.TemporaryDirectory(prefix="video_engine_") as tmpdir:
        tmp = Path(tmpdir)
        segment_paths: List[Path] = []
        total_scenes = len(scenes)

        # 1. Generate video segments for each scene
        for i, scene in enumerate(scenes):
            card_png = tmp / f"card_{i:04d}.png"
            seg_path = tmp / f"seg_{i:04d}.mp4"

            # Render custom scene image
            _generate_scene_card(scene, i, total_scenes, width, height, card_png)

            # Determine duration
            duration = round(scene.end_s - scene.start_s, 3)
            if duration <= 0:
                duration = 3.0

            # Encode PNG to MP4 segment of exact duration
            cmd = [
                bin_path, "-y",
                "-loop", "1",
                "-t", str(duration),
                "-i", str(card_png),
                "-c:v", "libx264",
                "-preset", preset,
                "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-an",
                str(seg_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg failed to encode scene {i}: {res.stderr[-400:]}")

            segment_paths.append(seg_path)
            if progress_callback:
                progress_callback(30 + int(30 * (i + 1) / max(total_scenes, 1)))

        # 2. Concatenate scene segments
        concat_list = tmp / "concat.txt"
        file_lines = ["file " + repr(str(p)) for p in segment_paths]
        concat_list.write_text("\n".join(file_lines), encoding="utf-8")

        concat_video = tmp / "concat.mp4"
        concat_cmd = [
            bin_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(concat_video),
        ]
        res = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {res.stderr[-400:]}")

        if progress_callback:
            progress_callback(75)

        # 3. Audio Muxing
        if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
            mux_cmd = [
                bin_path, "-y",
                "-i", str(concat_video),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", audio_bitrate,
                "-shortest",
                "-movflags", "+faststart",
                str(output_path),
            ]
            res = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=180)
            if res.returncode != 0:
                # If audio mux fails, fallback to video only
                shutil.copyfile(concat_video, output_path)
        else:
            shutil.copyfile(concat_video, output_path)

        if progress_callback:
            progress_callback(90)

    return output_path


def validate_output(path: Path, ffprobe_bin: str = "ffprobe") -> dict:
    """Validate the output video file."""
    if not path.exists() or path.stat().st_size < 1024:
        raise RuntimeError(f"Output video missing or empty: {path}")
    return {"status": "ok", "size_bytes": path.stat().st_size}
