from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from .claims import _STOPWORDS, topic_terms
from .keenable import KeenableClient
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
# Established newsrooms, fact-checkers, encyclopedias and non-partisan research bodies. Pages from anywhere else are
# never cited: low-authority sites are where tangential or wrong "evidence" came from in benchmarks.
REPUTABLE_DOMAINS = (
    "afp.com",
    "bbc.com",
    "bbc.co.uk",
    "npr.org",
    "pbs.org",
    "nytimes.com",
    "washingtonpost.com",
    "wsj.com",
    "theguardian.com",
    "ft.com",
    "economist.com",
    "bloomberg.com",
    "cnbc.com",
    "cnn.com",
    "cbsnews.com",
    "nbcnews.com",
    "abcnews.go.com",
    "usatoday.com",
    "latimes.com",
    "time.com",
    "axios.com",
    "politico.com",
    "thehill.com",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "lemonde.fr",
    "factcheck.org",
    "politifact.com",
    "snopes.com",
    "fullfact.org",
    "wikipedia.org",
    "crfb.org",
    "kff.org",
    "rand.org",
    "urban.org",
    "taxpolicycenter.org",
    "bipartisanpolicy.org",
    "brookings.edu",
    "cfr.org",
    "statista.com",
    "usafacts.org",
    "mayoclinic.org",
    "clevelandclinic.org",
    "cancer.org",
    "heart.org",
    "diabetes.org",
    "thelancet.com",
    "bmj.com",
    "nejm.org",
    "jamanetwork.com",
    "sciencedirect.com",
    "springer.com",
    "iea.org",
    "ipcc.ch",
    "nasa.gov",
    "noaa.gov",
    "unesco.org",
    "unicef.org",
    "wto.org",
    "icj-cij.org",
)

logger = logging.getLogger("vco.verification")

VERDICT_PROMPT = (
    'Fact-check this statement from a video using ONLY this page: "{claim}"\n'
    "Reply in exactly this format:\n"
    "VERDICT: SUPPORTED, CONTRADICTED, MISSING_CONTEXT, UNVERIFIED_DATA or ABSTAIN\n"
    "SUMMARY: 1-2 neutral third-person sentences, max {max_words} words, naming the source, its exact figures and "
    "their year "
    '(e.g. "Federal Reserve records show rates rose 0.75% in July 2022, not 1.5%."). No words like misleading, '
    "false or lie.\n"
    "QUOTE: one sentence copied verbatim from the page (max 30 words) backing the summary.\n"
    "PUBLISHER: the organization behind the page.\n"
    "SUPPORTED = the page confirms it; CONTRADICTED = the page shows it is wrong; MISSING_CONTEXT = true but the "
    "page adds context that changes its meaning; UNVERIFIED_DATA = on topic but lacks the specific figure. If the "
    "statement mixes several points, judge the main figure this page addresses. ABSTAIN if the page does not "
    "directly address it, is opinion or partisan, is a transcript or report of this same speech, or covers a "
    "different event, place or period. Never describe the speaker or what the page lacks."
)

DATE_CONTEXT = "Video date: {date}; use only data available by then.\n"
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_FIELD = re.compile(
    r"^\s*\**(VERDICT|SUMMARY|QUOTE|PUBLISHER)\**\s*:\s*\**\s*(.*?)\s*\**\s*$", re.IGNORECASE | re.MULTILINE
)
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
    if _matches(host, REPUTABLE_DOMAINS):
        return 1
    return 0


def rank_hits(hits: list[SearchHit]) -> list[SearchHit]:
    # Transcripts of the talk being checked can only echo the speaker.
    eligible = [hit for hit in hits if authority_score(hit.url) >= 1 and "transcript" not in (hit.title or "").lower()]
    return sorted(eligible, key=lambda hit: -authority_score(hit.url))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


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


# Summaries about the video itself are never evidence.
_SPEAKER_TALK = re.compile(r"\b(?:the (?:speaker|transcript|video|talk))\b", re.IGNORECASE)
# "This page has no data on X" is only acceptable as an UNVERIFIED_DATA note.
_NON_ANSWER = re.compile(
    r"\b(?:(?:does|do|did) not (?:\w+ )?(?:provide|contain|mention|discuss|address|include|cover)|"
    r"not (?:discussed|mentioned|addressed|provided)|(?:no|any) (?:\w+ ){0,2}(?:data|information|figures))\b",
    re.IGNORECASE,
)
_PAGE_REFERENCE = re.compile(
    r"\bthe (?:provided )?(?:page|text|source|document|article|study|paper|report|publication)\b",
    re.IGNORECASE,
)


# Units and filler shared by unrelated figures ("$500 million" in two different stories).
_GENERIC_TERMS = {"percent", "million", "billion", "trillion", "thousand", "year", "years", "people", "times"}


def _shared_terms(claim: Claim, text: str) -> set[str]:
    claim_terms = {
        t
        for t in _tokens(claim.quote)
        if t not in _STOPWORDS and t not in _GENERIC_TERMS and (len(t) > 3 or any(ch.isdigit() for ch in t))
    }
    return claim_terms & set(_tokens(text))


def is_relevant(claim: Claim, summary: str, citation: str) -> bool:
    """The summary must be about the claim: a shared figure plus a key term, or three key terms."""
    shared = _shared_terms(claim, f"{summary} {citation}")
    figures = {t for t in shared if any(ch.isdigit() for ch in t)}
    return (bool(figures) and len(shared - figures) >= 1) or len(shared - figures) >= 3


def usefulness(claim: Claim, category: Category, summary: str, citation: str, url: str) -> int:
    """How much a note tells the viewer, 0-7: a firm verdict, the claim's own subject, concrete figures,
    and an institutional source. "This page has no data on X" scores low unless it states what the source reports."""
    score = 0 if category == Category.UNVERIFIED_DATA else 2
    has_figure = any(ch.isdigit() for ch in summary)
    if _NON_ANSWER.search(summary):
        score -= 1 if has_figure else 2
    evidence = f"{summary} {citation}"
    subject = {t for t in _shared_terms(claim, evidence) if not any(ch.isdigit() for ch in t)}
    score += min(len(subject), 3)
    claim_topics = topic_terms(claim.quote)
    if claim_topics and not claim_topics & topic_terms(evidence):
        score -= 1
    return score + has_figure + (authority_score(url) == 2)


def is_stale(published: str | None, claim: Claim, summary: str, max_age: int = 3) -> bool:
    """Figures from well before the video (e.g. 2017 overdose deaths against a 2024 claim) cannot contradict or
    confirm it, unless the speaker was talking about that period."""
    if not published:
        return False
    years = [int(y) for y in _YEAR.findall(summary)]
    if not years or _YEAR.search(claim.quote):
        return False
    return max(years) < int(published[:4]) - max_age


def postdates(published: str | None, summary: str) -> bool:
    """Evidence about years after the video was published cannot check what the speaker said at the time."""
    return bool(published) and any(int(year) > int(published[:4]) for year in _YEAR.findall(summary))


def is_circular(claim: Claim, citation: str) -> bool:
    """A citation that mostly repeats the speaker's own words is a transcript of the video, not evidence."""
    claim_tokens = set(_tokens(claim.quote))
    cited = set(_tokens(citation))
    return bool(claim_tokens) and len(claim_tokens & cited) / len(claim_tokens) >= 0.6


def parse_verdict(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in _FIELD.findall(text or ""):
        fields.setdefault(key.upper(), value.strip().strip('"“”').strip())
    return fields


class VerificationEngine:
    """Evidence and synthesis both come from Keenable: search, then fetch with an extraction prompt."""

    def __init__(
        self,
        keenable: KeenableClient,
        max_results: int = 10,
        snippet_max_length: int = 200,
        fetch_max_chars: int = 20000,
        max_words: int = 50,
        max_fetches: int = 3,
        concurrency: int = 4,
        min_usefulness: int = 3,
    ):
        self._keenable = keenable
        self._max_results = max_results
        self._snippet_max_length = snippet_max_length
        self._fetch_max_chars = fetch_max_chars
        self._max_words = max_words
        self._max_fetches = max_fetches
        self._min_usefulness = min_usefulness
        self._semaphore = asyncio.Semaphore(concurrency)

    async def verify_all(self, claims: list[Claim], published: str | None = None) -> list[Note]:
        results = await asyncio.gather(*(self.verify(claim, published) for claim in claims), return_exceptions=True)
        notes = [result for result in results if isinstance(result, Note)]
        for index, note in enumerate(notes, start=1):
            note.note_id = f"note_{index:03d}"
        return notes

    async def verify(self, claim: Claim, published: str | None = None) -> Note | None:
        async with self._semaphore:
            hits = rank_hits(
                await self._keenable.search_claims(claim.search_query, self._max_results, self._snippet_max_length)
            )
            # "No data on this figure" is only a fallback when no source gives a real verdict.
            fallback = None
            for hit in hits[: self._max_fetches]:
                note = await self._check_source(claim, hit, published)
                if note and note.category != Category.UNVERIFIED_DATA:
                    return note
                fallback = fallback or note
            return fallback

    @staticmethod
    def _reject(claim: Claim, hit: SearchHit, reason: str) -> None:
        logger.info("%s: no note from %s (%s)", claim.claim_id, domain_of(hit.url), reason)
        return None

    async def _check_source(self, claim: Claim, hit: SearchHit, published: str | None = None) -> Note | None:
        prompt = VERDICT_PROMPT.format(claim=claim.quote[:600], max_words=min(self._max_words, 40))
        if published:
            prompt = DATE_CONTEXT.format(date=published) + prompt
        # Prompted fetch first; the plain page, needed only to ground the quote, is fetched once there is a verdict.
        answer = await self._keenable.fetch_source_markdown(hit.url, self._fetch_max_chars, prompt=prompt)
        if not answer:
            return self._reject(claim, hit, "fetch failed")
        fields = parse_verdict(answer)
        try:
            category = Category(fields.get("VERDICT", "").upper().replace(" ", "_"))
        except ValueError:
            return self._reject(claim, hit, f"verdict {fields.get('VERDICT', 'missing')!r}: {answer[:120]!r}")
        citation = " ".join(fields.get("QUOTE", "").split())
        summary = enforce_brevity(fields.get("SUMMARY", ""), self._max_words)
        if not summary:
            return self._reject(claim, hit, "empty summary")
        if not is_relevant(claim, summary, citation):
            return self._reject(claim, hit, "summary unrelated to claim")
        if _SPEAKER_TALK.search(summary):
            return self._reject(claim, hit, f"summary about the video: {summary}")
        if _NON_ANSWER.search(summary) and category != Category.UNVERIFIED_DATA:
            return self._reject(claim, hit, f"non-answer summary: {summary}")
        if postdates(published, summary):
            return self._reject(claim, hit, f"evidence postdates the video: {summary}")
        if category != Category.MISSING_CONTEXT and is_stale(published, claim, summary):
            return self._reject(claim, hit, f"evidence predates the video: {summary}")
        if is_circular(claim, citation):
            return self._reject(claim, hit, "source repeats the speaker")
        score = usefulness(claim, category, summary, citation, hit.url)
        if score < self._min_usefulness:
            return self._reject(claim, hit, f"not useful enough ({score}): {summary}")
        page = await self._keenable.fetch_source_markdown(hit.url, self._fetch_max_chars)
        if not page:
            return self._reject(claim, hit, "fetch failed")
        if not citation_is_grounded(citation, page):
            return self._reject(claim, hit, "quote not found on page")
        summary = _PAGE_REFERENCE.sub("this source", summary)
        summary = summary[:1].upper() + summary[1:]
        publisher = fields.get("PUBLISHER", "")
        if not publisher or publisher.lower() not in page.lower():
            publisher = domain_of(hit.url)
        logger.info("%s: note from %s (%s, usefulness %d)", claim.claim_id, domain_of(hit.url), category.value, score)
        return Note(
            note_id="",
            start_time=claim.start_time,
            end_time=claim.end_time,
            category=category,
            extracted_claim=claim.quote,
            summary=summary,
            source=Source(
                title=(hit.title or domain_of(hit.url))[:200],
                publisher=publisher[:120],
                url=hit.url,
                citation=" ".join(citation.split()[:40]),
            ),
        )
