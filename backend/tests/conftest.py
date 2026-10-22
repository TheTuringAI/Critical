from __future__ import annotations

import json

import pytest

from app.models import TranscriptSegment


class FakeTranscripts:
    def __init__(self, segments: list[TranscriptSegment] | Exception):
        self._segments = segments

    async def fetch(self, video_id: str) -> list[TranscriptSegment]:
        if isinstance(self._segments, Exception):
            raise self._segments
        return self._segments


@pytest.fixture
def segments() -> list[TranscriptSegment]:
    lines = [
        "Good evening and welcome to the debate.",
        "I believe our country deserves better leadership.",
        "Last year the country lost ten percent of its jobs,",
        "a ten percent decline in employment.",
        "Frankly my opponent has no vision.",
        "And unemployment fell to 3.4 percent in January 2023.",
    ]
    return [TranscriptSegment(text=t, start=i * 14.0, duration=12.0) for i, t in enumerate(lines)]


def search_payload(*results: dict) -> str:
    return json.dumps({"query": "q", "mode": "pro", "results": list(results)})
