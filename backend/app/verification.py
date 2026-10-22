from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from .keenable import KeenableClient
from .llm import JsonLLM
from .models import Category, Claim, Note, SearchHit, Source

EXCLUDED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "quora.com",
    "pinterest.com",
    "linkedin.com",
    "medium.com",
    "substack.com",
)
INSTITUTIONAL_SUFFIXES = (".gov", ".mil", ".edu", ".int", ".gov.uk", ".europa.eu", ".gc.ca", ".gov.au")
INSTITUTIONAL_DOMAINS = (
    "un.org",
    "who.int",
    "worldbank.org",
    "imf.org",
    "oecd.org",
    "federalreserve.gov",
    "census.gov",
    "congress.gov",
    "supremecourt.gov",
    "ons.gov.uk",
    "eurostat.ec.europa.eu",
    "reuters.com",
    "apnews.com",
    "britannica.com",
    "nature.com",
    "science.org",
    "pewresearch.org",
    "ourworldindata.org",
)

VERIFY_SYSTEM_PROMPT = """You are an impartial fact-checking assistant writing context notes for video viewers.
You receive one claim made in a video and numbered evidence excerpts retrieved from the web.

Rules:
- Use ONLY the evidence provided. Never use outside knowledge to fill gaps.
- ABSTAIN if the evidence is ambiguous, partisan, off-topic, outdated for the claim, or insufficient,
  or if the claim is actually an opinion, prediction or value judgment. Abstaining is always acceptable.
- Otherwise choose exactly one category:
  SUPPORTED       - evidence confirms the claim as stated.
  CONTRADICTED    - evidence clearly shows the claim is false or materially wrong.
  MISSING_CONTEXT - the claim is technically accurate but omits context that changes its meaning.
  UNVERIFIED_DATA - authoritative sources exist but do not contain data that can confirm the specific figure.
- summary: 1 to 2 sentences, at most {max_words} words total. Clinical, neutral, third-person. Lead with the
  source ("Bureau of Labor Statistics data shows..."). State figures precisely. No adjectives like "misleading",
  "false", "lie", no moral judgment, no speculation about intent.
- citation: copy a short passage (max 30 words) VERBATIM from the chosen evidence excerpt that supports your summary.
- publisher: the organization behind the chosen source (e.g. "U.S. Bureau of Labor Statistics").

Return JSON: {{"decision": "EMIT" | "ABSTAIN", "category": "...", "summary": "...",
"source_index": <int>, "citation": "...", "publisher": "...", "source_title": "..."}}"""

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def authority_score(url: str) -> int:
    host = domain_of(url)
    if _matches(host, EXCLUDED_DOMAINS):
        return -1
    if host.endswith(INSTITUTIONAL_SUFFIXES) or _matches(host, INSTITUTIONAL_DOMAINS):
        return 2
    if host.endswith(".org"):
        return 1
    return 0


def rank_hits(hits: list[SearchHit]) -> list[SearchHit]:
    eligible = [hit for hit in hits if authority_score(hit.url) >= 0]
    return sorted(eligible, key=lambda hit: -authority_score(hit.url))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def relevant_excerpt(markdown: str, claim: Claim, max_chars: int = 2500) -> str:
    """Keeps only paragraphs/table rows that share keywords or figures with the claim."""
    keywords = {t for t in _tokens(f"{claim.quote} {claim.search_query}") if len(t) > 3 or any(c.isdigit() for c in t)}
    blocks = [block.strip() for block in re.split(r"\n\s*\n|\n(?=\|)", markdown) if block.strip()]
    scored = []
    for position, block in enumerate(blocks):
        overlap = len(keywords.intersection(_tokens(block)))
        if overlap:
            scored.append((overlap, position, block))
    picked: list[tuple[int, str]] = []
    total = 0
    for _, position, block in sorted(scored, key=lambda item: (-item[0], item[1])):
        block = block[:800]
        if total + len(block) > max_chars:
            break
        picked.append((position, block))
        total += len(block)
    return "\n\n".join(block for _, block in sorted(picked))


def enforce_brevity(summary: str, max_words: int) -> str:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(" ".join(summary.split())) if s.strip()][:2]
    kept: list[str] = []
    for sentence in sentences:
        if len(" ".join(kept + [sentence]).split()) > max_words:
            break
        kept.append(sentence)
    if not kept and sentences:
        words = sentences[0].split()[:max_words]
        return " ".join(words).rstrip(",;:") + "…"
    return " ".join(kept)


def citation_is_grounded(citation: str, evidence: str) -> bool:
    cited, source = _tokens(citation), _tokens(evidence)
    if len(cited) < 4:
        return False
    if " ".join(cited) in " ".join(source):
        return True
    window = len(cited)
    cited_set = set(cited)
    best = 0.0
    for start in range(0, max(1, len(source) - window + 1)):
        overlap = len(cited_set.intersection(source[start : start + window])) / len(cited_set)
        best = max(best, overlap)
        if best >= 0.85:
            return True
    return False


class VerificationEngine:
    def __init__(
        self,
        keenable: KeenableClient,
        llm: JsonLLM,
        max_results: int = 3,
        snippet_max_length: int = 200,
        fetch_max_chars: int = 20000,
        max_words: int = 50,
        max_fetches: int = 2,
        concurrency: int = 4,
    ):
        self._keenable = keenable
        self._llm = llm
        self._max_results = max_results
        self._snippet_max_length = snippet_max_length
        self._fetch_max_chars = fetch_max_chars
        self._max_words = max_words
        self._max_fetches = max_fetches
        self._semaphore = asyncio.Semaphore(concurrency)

    async def verify_all(self, claims: list[Claim]) -> list[Note]:
        results = await asyncio.gather(*(self.verify(claim) for claim in claims), return_exceptions=True)
        notes = [result for result in results if isinstance(result, Note)]
        for index, note in enumerate(notes, start=1):
            note.note_id = f"note_{index:03d}"
        return notes

    async def verify(self, claim: Claim) -> Note | None:
        async with self._semaphore:
            hits = rank_hits(
                await self._keenable.search_claims(claim.search_query, self._max_results, self._snippet_max_length)
            )
            if not hits:
                return None
            evidence = await self._gather_evidence(claim, hits)
            if not evidence:
                return None
            return await self._synthesize(claim, evidence)

    async def _gather_evidence(self, claim: Claim, hits: list[SearchHit]) -> list[tuple[SearchHit, str]]:
        to_fetch = [hit for hit in hits if authority_score(hit.url) >= 1][: self._max_fetches]
        pages = await asyncio.gather(
            *(self._keenable.fetch_source_markdown(hit.url, self._fetch_max_chars) for hit in to_fetch)
        )
        fetched = {hit.url: page for hit, page in zip(to_fetch, pages, strict=True)}
        evidence = []
        for hit in hits:
            parts = [hit.snippet] if hit.snippet else []
            page = fetched.get(hit.url)
            if page:
                excerpt = relevant_excerpt(page, claim)
                if excerpt:
                    parts.append(excerpt)
            if parts:
                evidence.append((hit, "\n".join(parts)))
        return evidence

    async def _synthesize(self, claim: Claim, evidence: list[tuple[SearchHit, str]]) -> Note | None:
        blocks = "\n\n".join(
            f"[{i}] {hit.title} ({domain_of(hit.url)})"
            + (f" published {hit.published_at[:10]}" if hit.published_at else "")
            + f"\n{text}"
            for i, (hit, text) in enumerate(evidence, start=1)
        )
        user = f'Claim (said in the video): "{claim.quote}"\n\nEvidence:\n{blocks}'
        data = await self._llm.complete_json(VERIFY_SYSTEM_PROMPT.format(max_words=self._max_words), user)

        if str(data.get("decision", "")).upper() != "EMIT":
            return None
        try:
            category = Category(str(data.get("category", "")).upper())
            source_index = int(data.get("source_index", 0))
        except (ValueError, TypeError):
            return None
        if not 1 <= source_index <= len(evidence):
            return None
        hit, evidence_text = evidence[source_index - 1]
        citation = " ".join(str(data.get("citation", "")).split())
        summary = enforce_brevity(str(data.get("summary", "")), self._max_words)
        if not summary or not citation_is_grounded(citation, evidence_text):
            return None
        return Note(
            note_id="",
            start_time=claim.start_time,
            end_time=claim.end_time,
            category=category,
            extracted_claim=claim.quote,
            summary=summary,
            source=Source(
                title=str(data.get("source_title") or hit.title or domain_of(hit.url))[:200],
                publisher=str(data.get("publisher") or domain_of(hit.url))[:120],
                url=hit.url,
                citation=" ".join(citation.split()[:40]),
            ),
        )
