from app.models import Claim, SearchHit
from app.verification import (
    authority_score,
    citation_is_grounded,
    enforce_brevity,
    is_circular,
    is_relevant,
    parse_verdict,
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
    assert [h.url for h in rank_hits(hits)] == ["https://www.bls.gov/a", "https://blog.example.com/a"]


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
    assert is_relevant(CLAIM, "BLS data shows a rate of 3.4 percent.", "The rate was 3.4 percent.")
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
