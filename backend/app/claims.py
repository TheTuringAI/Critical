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
_MULTIPLIER = re.compile(
    r"\b(?:twice|double|triple|half of|(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten) times)\b",
    re.IGNORECASE,
)
_STATISTIC = re.compile(
    r"\b(?:leading cause|causes?|caused by|deaths?|dying|died|mortality|the amount of|the number of|majority of|"
    r"most people|rate of|record high|record low)\b",
    re.IGNORECASE,
)
# Strong opinion / prediction markers only: weak hedges like "would" leak in from neighbouring caption lines.
_OPINION = re.compile(
    r"\b(?:i think|i believe|i feel|in my opinion|we should|they should|you should|i hope|i want|we will|"
    r"we're going to|gonna)\b",
    re.IGNORECASE,
)
# Subjects people make checkable statements about. A topic word alone is not a claim; it needs a change,
# comparison, superlative, year, law or attribution next to it ("violent crime rose", "the largest tax cut").
_TOPIC_TERMS = {
    "economy": "economy economic gdp recession depression inflation deflation prices cost-of-living interest-rates "
    "mortgage mortgages wage wages salary salaries income incomes minimum-wage poverty jobs unemployment employment "
    "jobless layoffs workers labor-force manufacturing factories exports imports trade-deficit deficit deficits debt "
    "national-debt budget spending stock-market nasdaq housing home-prices rent gas-prices gasoline oil "
    "small-business small-businesses billionaires millionaires middle-class wealth gross-domestic-product",
    "taxes": "tax taxes tax-cut tax-cuts tax-rate tax-rates tariff tariffs irs corporate-tax income-tax",
    "health": "cancer lung-cancer diabetes obesity heart-disease heart-attack stroke vaccine vaccines vaccinated "
    "vaccination covid pandemic virus disease diseases overdose overdoses fentanyl opioid opioids insulin "
    "drug-prices prescription-drugs medicare medicaid obamacare affordable-care-act health-insurance uninsured "
    "hospital hospitals life-expectancy abortion abortions smoking smokers cigarette cigarettes tobacco vaping "
    "alcohol suicide suicides autism infant-mortality calories sugar cholesterol blood-pressure dna genes genetic",
    "crime": "crime crimes violent-crime murder murders homicide homicides shooting shootings gun-violence guns "
    "firearm firearms police arrests prison prisons incarceration inmates convicted conviction indicted felony "
    "felonies supreme-court constitution unconstitutional",
    "immigration": "immigrant immigrants immigration migrant migrants border illegal-aliens undocumented asylum "
    "deportation deportations deported refugee refugees visa visas citizenship green-card",
    "climate": "climate climate-change global-warming emissions carbon carbon-dioxide co2 temperature temperatures "
    "sea-level sea-levels renewable renewables solar wind-power nuclear-power coal natural-gas fossil-fuel "
    "fossil-fuels electric-vehicles wildfire wildfires hurricane hurricanes drought droughts floods pollution "
    "glaciers",
    "elections": "election elections voter voters votes voting ballot ballots turnout electoral-college polls "
    "approval-rating congress senate house-of-representatives legislation vetoed veto administration president "
    "governor federal government-shutdown",
    "war": "war wars military troops soldiers veteran veterans nato nuclear-weapons missile missiles invasion "
    "invaded casualties terrorist terrorists terrorism ukraine russia china israel gaza iran sanctions "
    "foreign-aid defense-spending army navy",
    "education": "school schools student students teacher teachers college colleges university universities "
    "tuition student-loans student-debt graduation-rate literacy test-scores",
    "society": "population births birth-rate fertility marriage divorce homeless homelessness crime-rate census "
    "life-span world-record scientists study studies research",
}


def _phrases_pattern(phrases: list[str]) -> re.Pattern[str]:
    # Longest phrases first so "lung cancer" wins over "cancer"; a hyphen matches spaces or hyphens.
    ordered = sorted(set(phrases), key=len, reverse=True)
    alternatives = "|".join(re.escape(p).replace(r"\-", r"[\s-]+") for p in ordered)
    return re.compile(r"\b(?:" + alternatives + r")\b", re.IGNORECASE)


_TOPIC = _phrases_pattern([term for terms in _TOPIC_TERMS.values() for term in terms.split()])
# Changes, comparisons and superlatives turn a topic mention into something that can be checked.
_CHANGE = re.compile(
    r"\b(?:increased?|increasing|decreased?|decreasing|rose|risen|rising|fell|fallen|falling|dropped|"
    r"declined?|declining|grew|grown|shrank|cut|raised|doubled|tripled|quadrupled|halved|soared|skyrocketed|"
    r"plummeted|collapsed|surged|spiked|jumped|lost|created|added|signed|passed|banned|repealed|voted|"
    r"approved|vetoed|killed|invented|discovered|proved|proven|highest|lowest|largest|biggest|smallest|worst|"
    r"best|fastest|slowest|most|least|first time|never before|in history|ever recorded|record|more than|"
    r"less than|fewer than|higher than|lower than|bigger than|as many as|as much as|compared to|since|"
    r"every year|per year|a year|a day|per capita|every day|causes?|leads? to|linked to|responsible for)\b",
    re.IGNORECASE,
)


def topic_terms(text: str) -> set[str]:
    """Checkable subjects mentioned in a text ("violent crime", "insulin"), normalised for comparison."""
    return {re.sub(r"[\s-]+", " ", m.group(0).lower()) for m in _TOPIC.finditer(text)}


_SENTENCE_END = re.compile(r"[.!?]$")
_STOPWORDS = set(
    "a an the and or but if of to in on at by for with from as is are was were be been being this that these those it "
    "its we our you your they their he she his her i me my us them so than then there here what which who whom whose "
    "when where why how all any both each few more most other some such no nor not only own same too very can will "
    "just do does did have has had about into over after before again further once also because while up down out off "
    "well like know right now really actually say said says going get got one let tell something nothing nobody "
    "anything everything everybody somebody thing things yet even still ever never mean okay yeah oh guys "
    "think thought want look see make made come came go went pulled put take took give gave".split()
)


def _score(text: str) -> int:
    if text.endswith("?") or _OPINION.search(text):
        return 0
    has_figure = bool(_NUMBER.search(text) or _WORD_NUMBER.search(text) or _MONEY.search(text))
    has_multiplier = bool(_MULTIPLIER.search(text))
    has_statistic = bool(_STATISTIC.search(text))
    has_topic = bool(_TOPIC.search(text))
    has_year, has_legal, has_attribution = (bool(p.search(text)) for p in (_YEAR, _LEGAL, _ATTRIBUTION))
    topical_change = has_topic and bool(_CHANGE.search(text))
    score = 2 * has_figure + 2 * has_multiplier + 2 * has_statistic
    score += has_year + has_legal + has_attribution + has_topic + topical_change
    if has_figure or has_multiplier or has_statistic or (has_legal and has_year):
        return score
    if has_topic and (topical_change or has_year or has_legal or has_attribution):
        return score
    return 0


# Auto-captions drop thousands separators: "800 000 jobs" -> "800,000 jobs".
_DIGIT_GROUPS = re.compile(r"\b(\d{1,3}) (\d{3})\b")


def _anchor_offset(text: str) -> int:
    """Character offset of the first checkable anchor (figure, multiplier, statistic...)."""
    patterns = (_NUMBER, _WORD_NUMBER, _MONEY, _MULTIPLIER, _STATISTIC, _YEAR, _LEGAL, _ATTRIBUTION, _TOPIC)
    offsets = [m.start() for p in patterns if (m := p.search(text))]
    return min(offsets, default=len(text))


def _claim_focus(text: str, lead_chars: int = 40) -> str:
    """The claim text from shortly before its first anchor: drops conversational preamble from search queries."""
    cut = text.rfind(" ", 0, max(0, _anchor_offset(text) - lead_chars))
    return text[cut + 1 :] if cut >= 0 else text


def build_search_query(text: str, max_terms: int = 8, min_terms: int = 6) -> str:
    """Figures, checkable subjects, changes and names first; other words only to pad short queries, nearest first."""
    key_spans = [m.span() for p in (_TOPIC, _CHANGE, _LEGAL, _ATTRIBUTION) for m in p.finditer(text)]
    key: list[tuple[int, int, str]] = []
    filler: list[tuple[int, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"[$€£]?\d[\d,.]*%?|[A-Za-z][A-Za-z'-]+", text):
        word = match.group(0).strip("'-")
        if word.lower() in _STOPWORDS or len(word) < 2 or word.lower() in seen:
            continue
        seen.add(word.lower())
        if any(ch.isdigit() for ch in word):
            key.append((0, match.start(), word))
        elif word[0].isupper() or any(a <= match.start() < b for a, b in key_spans):
            key.append((1, match.start(), word))
        else:
            filler.append((match.start(), word))
    chosen = [(pos, word) for _, pos, word in sorted(key)[:max_terms]]
    anchors = [pos for pos, _ in chosen] or [0]
    filler.sort(key=lambda f: min(abs(f[0] - a) for a in anchors))
    chosen += filler[: max(0, min_terms - len(chosen))]
    return " ".join(word for _, word in sorted(chosen))


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


def _caption_windows(segments: list[TranscriptSegment], min_words: int = 30) -> list[tuple[str, float, float]]:
    # Speakers usually finish a claim after its anchor ("three times as many ... dying from smoking"), so each
    # window starts one caption line early and extends forward.
    windows = []
    for index in range(len(segments)):
        first = max(0, index - 1)
        last = index
        while last < len(segments) - 1 and sum(len(s.text.split()) for s in segments[first : last + 1]) < min_words:
            last += 1
        text = " ".join(s.text for s in segments[first : last + 1])
        windows.append((text, segments[first].start, segments[last].end))
    return windows


def _same_claim(a: str, b: str) -> bool:
    """Overlapping caption windows describe the same claim when they share most of their words."""
    words_a, words_b = set(a.lower().split()), set(b.lower().split())
    return len(words_a & words_b) / max(1, min(len(words_a), len(words_b))) >= 0.5


class ClaimExtractor:
    def __init__(self, max_claims: int = 12, min_words: int = 8, max_words: int = 45):
        self._max_claims = max_claims
        self._min_words = min_words
        self._max_words = max_words

    async def extract(self, segments: list[TranscriptSegment]) -> list[Claim]:
        candidates = []
        for sentence, start, end in split_sentences(segments):
            text = _DIGIT_GROUPS.sub(r"\1,\2", _claim_focus(sentence))
            words = len(text.split())
            score = _score(text)
            if score and self._min_words <= words <= self._max_words:
                candidates.append((score, start, end, text))
        top: list[tuple[int, float, float, str]] = []
        # Among equally strong windows, prefer the one whose anchor comes earliest (least preamble).
        for candidate in sorted(candidates, key=lambda c: (-c[0], _anchor_offset(c[3]), c[1])):
            if all(not _same_claim(candidate[3], kept[3]) for kept in top):
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
