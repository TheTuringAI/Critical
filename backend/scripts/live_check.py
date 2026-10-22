"""Runs the real pipeline (YouTube captions + Keenable) on one or more video IDs and prints the notes."""

import asyncio
import json
import sys
import time

import httpx

from app.config import Settings
from app.main import build_pipeline


async def main(video_ids: list[str]) -> None:
    settings = Settings()
    async with httpx.AsyncClient(timeout=60.0) as http:
        pipeline = build_pipeline(settings, http)
        for video_id in video_ids:
            started = time.monotonic()
            segments = await pipeline.transcripts.fetch(video_id)
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
    asyncio.run(main(sys.argv[1:]))
