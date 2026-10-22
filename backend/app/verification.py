from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from .claims import _STOPWORDS
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
    'You are an impartial fact-checker. A speaker in a video said: "{claim}"\n'
    "Using ONLY the content of this page, reply in exactly this format and nothing else:\n"
    "VERDICT: one of SUPPORTED, CONTRADICTED, MISSING_CONTEXT, UNVERIFIED_DATA, ABSTAIN\n"
    "SUMMARY: 1 to 2 neutral, third-person sentences, at most {max_words} words in total, naming the source and "
    'stating exact figures (e.g. "Federal Reserve records indicate rates rose 0.75% in July 2022, not 1.5% as '
    'stated."). No judgmental words such as misleading, false or lie.\n'
    "QUOTE: one sentence copied verbatim from the page (max 30 words) that supports the summary.\n"
    "PUBLISHER: the organization that published this page.\n"
    "Meanings: SUPPORTED = the page confirms the claim; CONTRADICTED = the page clearly shows it is wrong; "
    "MISSING_CONTEXT = accurate but omits context that changes its meaning; UNVERIFIED_DATA = the page is on topic "
    "but has no data confirming the specific figure. If the speaker's words mix several statements, judge only the "
    "main factual figure or statement that this page addresses. Reply ABSTAIN if the page does not directly "
    "address it, "
    "is opinion or partisan, or the data is ambiguous. Also reply ABSTAIN if the page is a transcript, summary or "
    "news report of this same talk, video or speech (it cannot independently verify the speaker). Never describe "
    "the speaker or what the page does not contain. The page must cover the same event, place and time period as the "
    "claim; never compare against figures from a different year or event. Abstaining is always acceptable."
)

DATE_CONTEXT = "The video was published on {date}; judge the claim as of that date, not with data from later years.\n"
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
    ):
        self._keenable = keenable
        self._max_results = max_results
        self._snippet_max_length = snippet_max_length
        self._fetch_max_chars = fetch_max_chars
        self._max_words = max_words
        self._max_fetches = max_fetches
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
        page, answer = await asyncio.gather(
            self._keenable.fetch_source_markdown(hit.url, self._fetch_max_chars),
            self._keenable.fetch_source_markdown(hit.url, self._fetch_max_chars, prompt=prompt),
        )
        if not page or not answer:
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
        if not citation_is_grounded(citation, page):
            return self._reject(claim, hit, "quote not found on page")
        if not is_relevant(claim, summary, citation):
            return self._reject(claim, hit, "summary unrelated to claim")
        if _SPEAKER_TALK.search(summary):
            return self._reject(claim, hit, f"summary about the video: {summary}")
        if _NON_ANSWER.search(summary) and (
            category != Category.UNVERIFIED_DATA or len(_shared_terms(claim, summary)) < 3
        ):
            return self._reject(claim, hit, f"non-answer summary: {summary}")
        if postdates(published, summary):
            return self._reject(claim, hit, f"evidence postdates the video: {summary}")
        summary = _PAGE_REFERENCE.sub("this source", summary)
        summary = summary[:1].upper() + summary[1:]
        if is_circular(claim, citation):
            return self._reject(claim, hit, "source repeats the speaker")
        publisher = fields.get("PUBLISHER", "")
        if not publisher or publisher.lower() not in page.lower():
            publisher = domain_of(hit.url)
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
