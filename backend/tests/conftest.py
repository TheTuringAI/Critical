from __future__ import annotations

import json
from typing import Any

import pytest

from app.models import TranscriptSegment


class FakeLLM:
    """Routes prompts to canned responses: claim extraction vs. verification."""

    def __init__(self, claims: list[dict] | None = None, verdicts: dict[str, dict] | None = None):
        self.claims = claims or []
        self.verdicts = verdicts or {}
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if "VERIFIABLE FACTUAL CLAIMS" in system:
            indices = {int(line.split("]")[0][1:]) for line in user.splitlines() if line.startswith("[")}
            return {"claims": [c for c in self.claims if c["first_segment"] in indices]}
        for needle, verdict in self.verdicts.items():
            if needle in user:
                return verdict
        return {"decision": "ABSTAIN"}


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
