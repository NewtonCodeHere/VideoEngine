"""
Footage retrieval adapters.

Providers:
  - PexelsProvider  : Real stock footage via Pexels API (requires PEXELS_API_KEY)
  - MockProvider    : Deterministic mock for offline testing

The interface is a simple function:
    search(query, aspect_ratio, n) -> List[ClipCandidate]

All providers must populate licence metadata accurately.
Mock footage is clearly tagged with is_mock=True so the UI and manifest
can distinguish it from real footage.
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse
from typing import List, Optional, Protocol

import httpx

from app.models.schemas import AspectRatio, ClipInfo


# ── Protocol / Interface ──────────────────────────────────────────────────────

class FootageProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        aspect_ratio: AspectRatio = AspectRatio.r16x9,
        n: int = 5,
        avoid_ids: Optional[set] = None,
    ) -> List[ClipInfo]: ...


# ── Pexels Provider ───────────────────────────────────────────────────────────

_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
_PEXELS_LICENCE = "Pexels License"
_PEXELS_LICENCE_URL = "https://www.pexels.com/license/"
_PEXELS_TIMEOUT = 10  # seconds

_ORIENTATION_MAP = {
    AspectRatio.r16x9: "landscape",
    AspectRatio.r9x16: "portrait",
    AspectRatio.r1x1:  "square",
}


class PexelsProvider:
    name = "pexels"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("PEXELS_API_KEY is required for PexelsProvider")
        self._key = api_key

    def search(
        self,
        query: str,
        aspect_ratio: AspectRatio = AspectRatio.r16x9,
        n: int = 5,
        avoid_ids: Optional[set] = None,
    ) -> List[ClipInfo]:
        orientation = _ORIENTATION_MAP.get(aspect_ratio, "landscape")
        params = {
            "query": query,
            "per_page": min(n * 3, 40),  # fetch more, filter duplicates
            "orientation": orientation,
        }
        headers = {"Authorization": self._key}
        try:
            resp = httpx.get(
                _PEXELS_VIDEO_URL,
                params=params,
                headers=headers,
                timeout=_PEXELS_TIMEOUT,
            )
            resp.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError(
                f"Pexels API timed out after {_PEXELS_TIMEOUT}s for query '{query}'"
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise RuntimeError("Pexels API key is invalid or has been revoked.")
            raise RuntimeError(
                f"Pexels API returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            )

        data = resp.json()
        videos = data.get("videos", [])
        avoid_ids = avoid_ids or set()
        clips: List[ClipInfo] = []

        for video in videos:
            vid_id = str(video.get("id", ""))
            if vid_id in avoid_ids:
                continue
            if len(clips) >= n:
                break

            # Build attribution from Pexels photographer info
            photographer = video.get("user", {}).get("name", "Unknown")
            source_url = video.get("url", f"https://www.pexels.com/video/{vid_id}/")

            clip = ClipInfo(
                asset_id=vid_id,
                provider="pexels",
                source_url=source_url,
                licence_name=_PEXELS_LICENCE,
                licence_url=_PEXELS_LICENCE_URL,
                attribution=f"Video by {photographer} on Pexels ({source_url})",
                relevance_score=_estimate_relevance(query, video),
                selection_reason=f"Top Pexels result for query: '{query}'",
                is_mock=False,
            )
            clips.append(clip)

        return clips


def _estimate_relevance(query: str, video: dict) -> float:
    """
    Estimate relevance by checking query terms against video tags/description.
    Returns a float in [0, 1].
    """
    text = " ".join([
        video.get("url", ""),
        video.get("alt", ""),
        str(video.get("tags", "")),
    ]).lower()
    terms = query.lower().split()
    if not terms:
        return 0.5
    matches = sum(1 for t in terms if t in text)
    return round(matches / len(terms), 3)


# ── Mock Provider ─────────────────────────────────────────────────────────────

_MOCK_VIDEO_URLS = [
    "https://www.pexels.com/video/1448735/",
    "https://www.pexels.com/video/2499611/",
    "https://www.pexels.com/video/3195394/",
    "https://www.pexels.com/video/3963186/",
    "https://www.pexels.com/video/4065971/",
    "https://www.pexels.com/video/5087174/",
    "https://www.pexels.com/video/6804113/",
    "https://www.pexels.com/video/7242840/",
]


class MockProvider:
    """
    Deterministic mock footage provider for offline testing.
    NEVER used in production jobs unless FOOTAGE_PROVIDER=mock is explicitly set.
    All clips are tagged is_mock=True.
    """
    name = "mock"

    def search(
        self,
        query: str,
        aspect_ratio: AspectRatio = AspectRatio.r16x9,
        n: int = 5,
        avoid_ids: Optional[set] = None,
    ) -> List[ClipInfo]:
        avoid_ids = avoid_ids or set()
        clips: List[ClipInfo] = []
        # Use a hash of the query to deterministically pick clips
        seed = int(hashlib.md5(query.encode()).hexdigest(), 16)
        indices = [(seed + i) % len(_MOCK_VIDEO_URLS) for i in range(n * 2)]

        for idx in indices:
            if len(clips) >= n:
                break
            asset_id = f"mock_{idx}"
            if asset_id in avoid_ids:
                continue
            clips.append(ClipInfo(
                asset_id=asset_id,
                provider="mock",
                source_url=_MOCK_VIDEO_URLS[idx],
                licence_name="Mock (Test Only)",
                licence_url="https://example.com/mock-licence",
                attribution="Mock footage – not real stock video",
                relevance_score=round(0.5 + 0.1 * (len(query) % 5), 3),
                selection_reason=f"Mock clip for offline testing (query: '{query}')",
                is_mock=True,
            ))

        return clips


# ── Factory ───────────────────────────────────────────────────────────────────

def get_footage_provider(provider_name: str, pexels_api_key: Optional[str] = None) -> FootageProvider:
    if provider_name == "pexels":
        if not pexels_api_key:
            raise ValueError(
                "PEXELS_API_KEY environment variable is not set. "
                "Set it in your .env file or use FOOTAGE_PROVIDER=mock for testing."
            )
        return PexelsProvider(pexels_api_key)
    elif provider_name == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Unknown footage provider: '{provider_name}'")
