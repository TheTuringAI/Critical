from app.models import Claim, SearchHit
from app.verification import (
    authority_score,
    citation_is_grounded,
    enforce_brevity,
    is_circular,
    is_relevant,
    parse_verdict,
    postdates,
    rank_hits,
)


def test_authority_score_prefers_institutions_and_excludes_social():
    assert authority_score("https://www.bls.gov/news.release/empsit.nr0.htm") == 2
    assert authority_score("https://data.worldbank.org/indicator") == 2
    assert authority_score("https://www.factcheck.org/x") == 1
    assert authority_score("https://example.com/blog") == 0
    assert authority_score("https://www.youtube.com/watch?v=abc") == -1
    assert authority_score("https://x.com/someone/status/1") == -1


def test_rank_hits_drops_excluded_and_orders_by_authority():
    hits = [
        SearchHit(url="https://blog.example.com/a"),
        SearchHit(url="https://reddit.com/r/x"),
        SearchHit(url="https://www.bls.gov/a"),
    ]
    hits.append(SearchHit(url="https://www.reuters.com/b"))
    hits.append(SearchHit(url="https://en.wikipedia.org/wiki/Jobs"))
    hits.append(SearchHit(url="https://rev.com/x", title="Debate transcript"))
    assert [h.url for h in rank_hits(hits)] == [
        "https://www.bls.gov/a",
        "https://www.reuters.com/b",
        "https://en.wikipedia.org/wiki/Jobs",
    ]


def test_enforce_brevity_keeps_max_two_sentences_within_word_limit():
    text = "First sentence here. Second sentence is fine. Third sentence must go."
    assert enforce_brevity(text, 50) == "First sentence here. Second sentence is fine."
    long_second = "Short one. Then " + " ".join(["word"] * 60) + "."
    assert enforce_brevity(long_second, 50) == "Short one."
    assert enforce_brevity(" ".join(["w"] * 80), 10).endswith("…")
    assert len(enforce_brevity(" ".join(["w"] * 80), 10).split()) == 10


def test_citation_grounding_requires_verbatim_like_overlap():
    evidence = "Total nonfarm payroll employment rose by 2.7 million in 2023, the agency said."
    assert citation_is_grounded("Total nonfarm payroll employment rose by 2.7 million in 2023.", evidence)
    assert not citation_is_grounded("Employment fell by 10 percent in 2023 across sectors.", evidence)
    assert not citation_is_grounded("rose by", evidence)


def test_parse_verdict_tolerates_markdown_and_quotes():
    text = '**VERDICT:** CONTRADICTED\nSUMMARY: BLS data shows growth.\nQUOTE: "Employment rose."\nPUBLISHER: BLS'
    assert parse_verdict(text) == {
        "VERDICT": "CONTRADICTED",
        "SUMMARY": "BLS data shows growth.",
        "QUOTE": "Employment rose.",
        "PUBLISHER": "BLS",
    }
    assert parse_verdict("") == {}


CLAIM = Claim(
    claim_id="c",
    quote="unemployment fell to 3.4 percent in January 2023",
    start_time=0,
    end_time=6,
    search_query="unemployment fell 3.4 percent January 2023",
)


def test_relevance_requires_shared_figure_or_terms():
    assert is_relevant(CLAIM, "BLS data shows unemployment was 3.4 percent.", "The rate was 3.4 percent.")
    assert not is_relevant(CLAIM, "Inflation was 3.4 percent.", "Prices rose 3.4 percent.")
    assert not is_relevant(CLAIM, "A list of sovereign states in 1963.", "Countries are listed.")


def test_transcripts_of_the_same_video_are_circular():
    assert is_circular(CLAIM, "As he said, unemployment fell to 3.4 percent in January 2023.")
    assert not is_circular(CLAIM, "The unemployment rate was 3.4 percent, BLS reported.")


def test_non_answer_patterns():
    from app.verification import _NON_ANSWER, _SPEAKER_TALK

    assert _NON_ANSWER.search("but the text does not contain data comparing deaths")
    assert _SPEAKER_TALK.search("The speaker claims rates rose.")
    assert not _SPEAKER_TALK.search("The CDC states that smoking causes lung cancer.")
    assert not _NON_ANSWER.search("BLS data shows 3.4 percent in January 2023.")


def test_postdates_rejects_evidence_from_after_the_video():
    assert postdates("2024-03-07", "USAFacts records show wages grew 3.6% from September 2025 to September 2026.")
    assert not postdates("2024-03-07", "BLS data shows unemployment was 3.7% in 2023.")
    assert not postdates(None, "Data from 2026.")


def test_shared_amount_alone_is_not_relevant():
    claim = Claim(
        claim_id="claim_001",
        quote="they raised $500 million in a 10-year period and we would wipe out the debt",
        start_time=0,
        end_time=5,
        search_query="raised $500 million debt",
    )
    assert not is_relevant(claim, "Bloomberg reports Batista secured $500 million from investors.", "He secured funds.")
