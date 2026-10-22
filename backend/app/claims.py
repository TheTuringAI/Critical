from __future__ import annotations

import re

from .models import Claim, TranscriptSegment

# Rule-based extraction: no LLM. A sentence qualifies only if it carries a concrete, checkable anchor
# (figure, percentage, money, year, legislation, attribution) and no opinion/speculation marker.
_NUMBER = re.compile(r"\b\d[\d,.]*\s*(?:%|percent|per cent|million|billion|trillion|thousand)?", re.IGNORECASE)
_WORD_NUMBER = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred|half)\s+"
    r"(?:percent|per cent|million|billion|trillion|thousand)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_MONEY = re.compile(r"[$€£]\s?\d")
_LEGAL = re.compile(r"\b(?:act|bill|law|amendment|treaty|ruling|resolution|executive order|statute)\b", re.IGNORECASE)
_ATTRIBUTION = re.compile(
    r"\b(?:according to|reported|data shows?|statistics show|census|survey found)\b", re.IGNORECASE
)
_OPINION = re.compile(
    r"\b(?:i think|i believe|i feel|in my opinion|we should|they should|should|would|could|might|maybe|perhaps|"
    r"probably|i hope|i want|we will|we're going to|gonna|imagine|if we|if you|let's)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?]$")
_STOPWORDS = set(
    "a an the and or but if of to in on at by for with from as is are was were be been being this that these those it "
    "its we our you your they their he she his her i me my us them so than then there here what which who whom whose "
    "when where why how all any both each few more most other some such no nor not only own same too very can will "
    "just do does did have has had about into over after before again further once also because while up down out off "
    "well like know right now really actually say said says going get got one".split()
)


def _score(text: str) -> int:
    if text.endswith("?") or _OPINION.search(text):
        return 0
    score = 0
    if _NUMBER.search(text) or _WORD_NUMBER.search(text) or _MONEY.search(text):
        score += 2
    if _YEAR.search(text):
        score += 1
    if _LEGAL.search(text):
        score += 1
    if _ATTRIBUTION.search(text):
        score += 1
    has_figure = bool(_NUMBER.search(text) or _WORD_NUMBER.search(text) or _MONEY.search(text))
    return score if has_figure or (_LEGAL.search(text) and _YEAR.search(text)) else 0


def build_search_query(text: str, max_terms: int = 8) -> str:
    terms: list[str] = []
    for raw in re.findall(r"[$€£]?\d[\d,.]*%?|[A-Za-z][A-Za-z'-]+", text):
        word = raw.strip("'-")
        if word.lower() in _STOPWORDS or len(word) < 2 or word.lower() in (t.lower() for t in terms):
            continue
        terms.append(word)
        if len(terms) >= max_terms:
            break
    return " ".join(terms)


def split_sentences(segments: list[TranscriptSegment], max_words: int = 40) -> list[tuple[str, float, float]]:
    """Merges caption fragments into sentences with start/end times.

    Auto-generated captions usually have no punctuation; there each caption line is a unit, widened with its
    neighbours until it reads as a short statement (~22-35 words).
    """
    if not segments:
        return []
    punctuated = sum(bool(_SENTENCE_END.search(s.text)) for s in segments) / len(segments) >= 0.2
    if not punctuated:
        return _caption_windows(segments)
    sentences: list[tuple[str, float, float]] = []
    buffer: list[str] = []
    start = 0.0
    for segment in segments:
        if not buffer:
            start = segment.start
        buffer.append(segment.text)
        text = " ".join(buffer)
        if _SENTENCE_END.search(segment.text) or len(text.split()) >= max_words:
            sentences.append((text, start, segment.end))
            buffer = []
    if buffer:
        sentences.append((" ".join(buffer), start, segments[-1].end))
    return sentences


def _caption_windows(segments: list[TranscriptSegment]) -> list[tuple[str, float, float]]:
    windows = []
    for index in range(len(segments)):
        first = last = index
        while sum(len(s.text.split()) for s in segments[first : last + 1]) < 22:
            if first > 0 and (last == len(segments) - 1 or index - first <= last - index):
                first -= 1
            elif last < len(segments) - 1:
                last += 1
            else:
                break
        text = " ".join(s.text for s in segments[first : last + 1])
        windows.append((text, segments[first].start, segments[last].end))
    return windows


class ClaimExtractor:
    def __init__(self, max_claims: int = 12, min_words: int = 6, max_words: int = 45):
        self._max_claims = max_claims
        self._min_words = min_words
        self._max_words = max_words

    async def extract(self, segments: list[TranscriptSegment]) -> list[Claim]:
        candidates = []
        for text, start, end in split_sentences(segments):
            words = len(text.split())
            score = _score(text)
            if score and self._min_words <= words <= self._max_words:
                candidates.append((score, start, end, text))
        top: list[tuple[int, float, float, str]] = []
        for candidate in sorted(candidates, key=lambda c: (-c[0], c[1])):
            if all(candidate[2] <= kept[1] or candidate[1] >= kept[2] for kept in top):
                top.append(candidate)
            if len(top) >= self._max_claims:
                break
        claims = []
        for index, (_, start, end, text) in enumerate(sorted(top, key=lambda c: c[1]), start=1):
            claims.append(
                Claim(
                    claim_id=f"claim_{index:03d}",
                    quote=text,
                    start_time=round(start, 3),
                    end_time=round(max(end, start + 6.0), 3),
                    search_query=build_search_query(text),
                )
            )
        return claims
