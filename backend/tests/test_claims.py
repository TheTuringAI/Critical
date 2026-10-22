import pytest

from app.claims import ClaimExtractor, build_search_query, split_sentences
from app.models import TranscriptSegment


def seg(text: str, start: float) -> TranscriptSegment:
    return TranscriptSegment(text=text, start=start, duration=4.0)


def test_split_sentences_merges_caption_fragments():
    sentences = split_sentences(
        [seg("Last year the country", 10), seg("lost ten percent of its jobs.", 14), seg("Next.", 18)]
    )
    assert sentences[0] == ("Last year the country lost ten percent of its jobs.", 10, 18.0)


@pytest.mark.asyncio
async def test_extractor_keeps_checkable_facts_and_ignores_opinions(segments):
    claims = await ClaimExtractor().extract(segments)
    quotes = [c.quote for c in claims]
    assert quotes == [
        "Last year the country lost ten percent of its jobs, a ten percent decline in employment.",
        "And unemployment fell to 3.4 percent in January 2023.",
    ]
    assert claims[0].start_time == 28.0 and claims[0].claim_id == "claim_001"
    assert "3.4" in claims[1].search_query and "2023" in claims[1].search_query


@pytest.mark.asyncio
async def test_opinions_and_predictions_produce_no_claims():
    segments = [
        seg("I think taxes are far too high.", 0),
        seg("We should cut spending by 20 percent next year.", 5),
        seg("Is unemployment really at 4 percent?", 10),
        seg("My opponent has no vision for this country.", 15),
    ]
    assert await ClaimExtractor().extract(segments) == []


def test_build_search_query_keeps_numbers_and_names():
    query = build_search_query("And unemployment fell to 3.4 percent in January 2023 according to the BLS.")
    assert query.split()[:3] == ["unemployment", "fell", "3.4"]
    assert "BLS" in query and "the" not in query.split()


@pytest.mark.asyncio
async def test_unpunctuated_auto_captions_yield_rhetorical_claims():
    lines = [
        "let me tell you something do you know",
        "that the amount of people dying from",
        "diabetes are three times as many people",
        "dying from smoking yet if I pulled a",
        "snicker bar nobody will say anything do",
        "you know that the leading cause of lung",
        "cancer is that actually a cigarette it's",
        "your DNA you could smoke for years and",
        "nothing would ever happen to you",
    ]
    claims = await ClaimExtractor().extract([seg(t, 46 + i * 3) for i, t in enumerate(lines)])
    text = " | ".join(c.quote for c in claims)
    assert "diabetes are three times as many people" in text
    assert "leading cause of lung" in text
