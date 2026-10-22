from __future__ import annotations

import asyncio

from .llm import JsonLLM
from .models import Claim, TranscriptSegment
from .transcript import chunk_segments

CLAIM_SYSTEM_PROMPT = """You extract VERIFIABLE FACTUAL CLAIMS from a timestamped English video transcript.

A claim qualifies ONLY if it asserts something checkable against public records:
- statistics, numbers, percentages, amounts, rankings
- dates and historical events
- laws, bills, votes, court rulings, official policies
- quotes or positions attributed to a named person or institution

STRICTLY IGNORE: opinions, value judgments, predictions, promises, hypotheticals, rhetorical questions,
personal anecdotes, vague statements ("things are getting worse"), and anything without a concrete checkable fact.
When in doubt, leave it out. Returning zero claims is a correct, common answer.

Each transcript line is formatted "[<segment_index>] <text>". Return JSON:
{"claims": [{"quote": "<the speaker's words, verbatim or minimally trimmed, max 30 words>",
             "first_segment": <int>, "last_segment": <int>,
             "search_query": "<5-12 precise keywords to verify the fact, naming the authoritative source if obvious,
                              e.g. 'US inflation rate 2022 Bureau of Labor Statistics'>"}]}"""


class ClaimExtractor:
    def __init__(self, llm: JsonLLM, chunk_seconds: int = 180, max_claims: int = 12, concurrency: int = 4):
        self._llm = llm
        self._chunk_seconds = chunk_seconds
        self._max_claims = max_claims
        self._semaphore = asyncio.Semaphore(concurrency)

    async def extract(self, segments: list[TranscriptSegment]) -> list[Claim]:
        chunks = chunk_segments(segments, self._chunk_seconds)
        results = await asyncio.gather(*(self._extract_chunk(segments, chunk) for chunk in chunks))
        claims: list[Claim] = []
        seen: set[str] = set()
        for chunk_claims in results:
            for claim in chunk_claims:
                key = _normalize(claim.quote)
                if key in seen or any(key in other or other in key for other in seen):
                    continue
                seen.add(key)
                claims.append(claim)
        claims.sort(key=lambda claim: claim.start_time)
        claims = claims[: self._max_claims]
        for index, claim in enumerate(claims, start=1):
            claim.claim_id = f"claim_{index:03d}"
        return claims

    async def _extract_chunk(self, segments: list[TranscriptSegment], indices: list[int]) -> list[Claim]:
        lines = "\n".join(f"[{i}] {segments[i].text}" for i in indices)
        async with self._semaphore:
            data = await self._llm.complete_json(CLAIM_SYSTEM_PROMPT, f"Transcript:\n{lines}")
        valid = set(indices)
        claims = []
        for raw in data.get("claims", []) if isinstance(data.get("claims"), list) else []:
            try:
                first, last = int(raw["first_segment"]), int(raw["last_segment"])
                quote, query = str(raw["quote"]).strip(), str(raw["search_query"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if first not in valid or last not in valid or not quote or not query:
                continue
            first, last = min(first, last), max(first, last)
            claims.append(
                Claim(
                    claim_id="",
                    quote=_truncate_words(quote, 30),
                    start_time=round(segments[first].start, 3),
                    end_time=round(max(segments[last].end, segments[first].start + 6.0), 3),
                    search_query=query[:200],
                )
            )
        return claims


def _normalize(text: str) -> str:
    return " ".join("".join(ch.lower() for ch in text if ch.isalnum() or ch.isspace()).split())


def _truncate_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]) + "…"
