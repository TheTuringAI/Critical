from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from .errors import NoCaptionsError, UpstreamError, VideoUnavailableError
from .models import TranscriptSegment

_WS = re.compile(r"\s+")
_NON_SPEECH = re.compile(r"\[(?:music|applause|laughter|inaudible|crosstalk)[^\]]*\]", re.IGNORECASE)


class TranscriptService:
    """Fetches English captions in memory only; nothing is cached or persisted."""

    def __init__(self, api: YouTubeTranscriptApi | None = None):
        self._api = api or YouTubeTranscriptApi()

    async def fetch(self, video_id: str) -> list[TranscriptSegment]:
        return await asyncio.to_thread(self._fetch_sync, video_id)

    def _fetch_sync(self, video_id: str) -> list[TranscriptSegment]:
        try:
            transcripts = self._api.list(video_id)
            try:
                transcript = transcripts.find_manually_created_transcript(["en", "en-US", "en-GB"])
            except NoTranscriptFound:
                transcript = transcripts.find_generated_transcript(["en", "en-US", "en-GB"])
            fetched = transcript.fetch()
        except (NoTranscriptFound, TranscriptsDisabled) as exc:
            raise NoCaptionsError("No English captions available for this video.") from exc
        except VideoUnavailable as exc:
            raise VideoUnavailableError("Video is unavailable.") from exc
        except CouldNotRetrieveTranscript as exc:
            raise UpstreamError(f"Could not retrieve captions: {type(exc).__name__}") from exc

        return clean_segments((s.text, s.start, s.duration) for s in fetched.snippets)


def clean_segments(lines: Iterable[tuple[str, float, float]]) -> list[TranscriptSegment]:
    """Drops non-speech markers and blank lines; raises NoCaptionsError if nothing is left."""
    segments = []
    for raw, start, duration in sorted(lines, key=lambda line: line[1]):
        text = _WS.sub(" ", _NON_SPEECH.sub(" ", raw)).strip()
        if text:
            segments.append(TranscriptSegment(text=text, start=round(start, 3), duration=round(duration, 3)))
    if not segments:
        raise NoCaptionsError("No English captions available for this video.")
    return segments


def chunk_segments(segments: list[TranscriptSegment], chunk_seconds: int, overlap: int = 2) -> list[list[int]]:
    """Group segment indices into time windows, overlapping by a few segments so claims are not cut."""
    chunks: list[list[int]] = []
    current: list[int] = []
    window_start = segments[0].start if segments else 0.0
    for index, segment in enumerate(segments):
        if current and segment.start - window_start >= chunk_seconds:
            chunks.append(current)
            current = current[-overlap:] if overlap else []
            window_start = segments[current[0]].start if current else segment.start
        current.append(index)
    if current:
        chunks.append(current)
    return chunks
