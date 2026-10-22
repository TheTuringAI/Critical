"""Runs the real pipeline (YouTube captions + Keenable) on video IDs and prints the notes.

Usage: live_check.py [--max-seconds N] [--transcript FILE.tsv] <video_id> [...]
A transcript file (start<TAB>text per line) skips YouTube, e.g. when YouTube rate-limits this IP.
"""

import asyncio
import json
import logging
import sys
import time

import httpx

from app.config import Settings
from app.main import build_pipeline
from app.models import TranscriptSegment


def load_tsv(path: str) -> list[TranscriptSegment]:
    rows = [line.split("\t", 1) for line in open(path, encoding="utf-8").read().splitlines() if line.strip()]
    starts = [float(start) for start, _ in rows]
    return [
        TranscriptSegment(
            text=text, start=start, duration=(starts[i + 1] if i + 1 < len(starts) else start + 3) - start
        )
        for i, (start, (_, text)) in enumerate(zip(starts, rows, strict=True))
    ]


logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main(video_ids: list[str], max_seconds: float | None = None, transcript: str | None = None) -> None:
    settings = Settings()
    async with httpx.AsyncClient(timeout=60.0) as http:
        pipeline = build_pipeline(settings, http)
        for video_id in video_ids:
            started = time.monotonic()
            segments = load_tsv(transcript) if transcript else await pipeline.transcripts.fetch(video_id)
            if max_seconds:
                segments = [s for s in segments if s.start < max_seconds]
            claims = await pipeline.extractor.extract(segments)
            notes = await pipeline.verifier.verify_all(claims)
            print(
                f"\n=== {video_id}: {len(segments)} segments, {len(claims)} claims, {len(notes)} notes, "
                f"{time.monotonic() - started:.1f}s"
            )
            for claim in claims:
                print(f"  claim {claim.start_time:7.1f}s | {claim.quote} | q={claim.search_query}")
            for note in notes:
                print(json.dumps(note.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = transcript_file = None
    while args and args[0].startswith("--"):
        flag, value, args = args[0], args[1], args[2:]
        if flag == "--max-seconds":
            limit = float(value)
        elif flag == "--transcript":
            transcript_file = value
    asyncio.run(main(args, limit, transcript_file))
