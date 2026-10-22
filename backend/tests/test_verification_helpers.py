from app.models import Claim, SearchHit
from app.transcript import chunk_segments
from app.verification import (
    authority_score,
    citation_is_grounded,
    enforce_brevity,
    rank_hits,
    relevant_excerpt,
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


def test_relevant_excerpt_keeps_matching_blocks_only():
    claim = Claim(
        claim_id="c",
        quote="unemployment fell to 3.4 percent",
        start_time=0,
        end_time=1,
        search_query="unemployment rate January 2023 BLS",
    )
    page = "Cookie banner text.\n\nThe unemployment rate fell to 3.4 percent in January 2023.\n\nSubscribe now."
    excerpt = relevant_excerpt(page, claim)
    assert "3.4 percent" in excerpt
    assert "Cookie" not in excerpt and "Subscribe" not in excerpt


def test_chunk_segments_overlaps_windows(segments):
    chunks = chunk_segments(segments, chunk_seconds=30, overlap=1)
    assert chunks[0] == [0, 1, 2]
    assert chunks[1][0] == 2
    assert sorted({i for c in chunks for i in c}) == list(range(len(segments)))
