"""Benchmarks the pipeline on a plain-text transcript (e.g. a published debate transcript).

Usage: bench_text.py [--autocaps] [--max-words N] [--published YYYY-MM-DD] [--extract-only] FILE

The text is split into ~8-word caption lines at ~150 words/minute. --autocaps strips punctuation and casing to mimic
YouTube auto-generated captions.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time

import httpx

from app.config import get_settings
from app.main import build_pipeline
from app.models import TranscriptSegment

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

_SPEAKER = re.compile(r"^\s*(?:\*\*)?[A-Z][A-Za-z .'\-]{1,40}(?:\*\*)?\s*:\s*(?:\*\*)?", re.M)


def to_segments(text: str, autocaps: bool, max_words: int | None) -> list[TranscriptSegment]:
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|https?://\S+|[#*_>`|]", " ", _SPEAKER.sub(" ", text))
    if autocaps:
        text = re.sub(r"[.,!?;:\"“”]", " ", text.lower())
    words = text.split()[:max_words] if max_words else text.split()
    seconds_per_word = 60 / 150
    return [
        TranscriptSegment(text=" ".join(words[i : i + 8]), start=i * seconds_per_word, duration=8 * seconds_per_word)
        for i in range(0, len(words), 8)
    ]


async def main(path: str, autocaps: bool, max_words: int | None, extract_only: bool, published: str | None) -> None:
    settings = get_settings()
    segments = to_segments(open(path, encoding="utf-8").read(), autocaps, max_words)
    async with httpx.AsyncClient() as http:
        pipeline = build_pipeline(settings, http)
        claims = await pipeline.extractor.extract(segments)
        print(f"=== {path}: {len(segments)} lines (~{segments[-1].end / 60:.0f} min), {len(claims)} claims")
        for claim in claims:
            print(f"  claim {claim.start_time:7.1f}s | {claim.quote} | q={claim.search_query}")
        if extract_only:
            return
        began = time.monotonic()
        notes = await pipeline.verifier.verify_all(claims, published)
        print(f"=== {len(notes)} notes in {time.monotonic() - began:.1f}s")
        for note in notes:
            print(f"  [{note.category.value}] {note.start_time:.0f}s {note.source.publisher}: {note.summary}")


if __name__ == "__main__":
    args = sys.argv[1:]
    autocaps = "--autocaps" in args
    extract_only = "--extract-only" in args
    limit = int(args[args.index("--max-words") + 1]) if "--max-words" in args else None
    published = args[args.index("--published") + 1] if "--published" in args else None
    asyncio.run(main(args[-1], autocaps, limit, extract_only, published))
