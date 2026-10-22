import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import NoCaptionsError
from app.keenable import KeenableClient
from app.main import Pipeline, create_app
from app.models import TranscriptSegment

from .conftest import FakeTranscripts

BASE = "https://api.keenable.ai"
BLS = "https://www.bls.gov/news.release/empsit.nr0.htm"
CITATION = "Total nonfarm payroll employment rose by 2.7 million in 2023."
PAGE = f"U.S. Bureau of Labor Statistics\n\n{CITATION} The unemployment rate was 3.4 percent in January 2023.\n\nFooter"
ANSWERS = {
    "ten percent of its jobs": "VERDICT: CONTRADICTED\nSUMMARY: Bureau of Labor Statistics data shows nonfarm payroll "
    "employment increased by 2.7 million jobs in 2023. It did not decline. This third sentence should be dropped.\n"
    f"QUOTE: {CITATION}\nPUBLISHER: U.S. Bureau of Labor Statistics",
    # Quote is not on the page: must be dropped by the grounding check.
    "3.4 percent": "VERDICT: SUPPORTED\nSUMMARY: BLS: 3.4%.\nQUOTE: Invented sentence.\nPUBLISHER: BLS",
}


def make_client(transcripts) -> TestClient:
    settings = Settings(keenable_api_key="keen_test")
    pipeline = Pipeline(settings, transcripts, KeenableClient("keen_test", BASE))
    return TestClient(create_app(settings, pipeline))


def fake_fetch(request: httpx.Request) -> httpx.Response:
    prompt = request.url.params.get("prompt")
    if not prompt:
        return httpx.Response(200, json={"url": BLS, "content": PAGE})
    answer = next((a for key, a in ANSWERS.items() if key in prompt), "VERDICT: ABSTAIN")
    return httpx.Response(200, json={"url": BLS, "content": answer})


def mock_keenable():
    results = [
        {"title": "Video", "url": "https://www.youtube.com/watch?v=x", "description": "", "snippet": "irrelevant"},
        {"title": "Employment Situation Summary", "url": BLS, "description": "", "snippet": "Payroll data."},
    ]
    search = respx.post(f"{BASE}/v1/search").mock(
        return_value=httpx.Response(200, json={"query": "q", "mode": "pro", "results": results})
    )
    fetch = respx.get(f"{BASE}/v1/fetch").mock(side_effect=fake_fetch)
    return search, fetch


@respx.mock
def test_analyze_uses_keenable_summaries_and_abstains_otherwise(segments):
    _, fetch = mock_keenable()
    with make_client(FakeTranscripts(segments)) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "language": "en"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["notes_count"] == 1
    note = body["notes"][0]
    assert note["note_id"] == "note_001"
    assert note["category"] == "CONTRADICTED"
    assert note["start_time"] == 28.0
    assert note["summary"].endswith("It did not decline.") and "third sentence" not in note["summary"]
    assert len(note["summary"].split()) <= 50
    assert note["source"]["url"] == BLS and note["source"]["citation"] == CITATION
    assert note["source"]["publisher"] == "U.S. Bureau of Labor Statistics"
    fetched = [call.request.url.params["url"] for call in fetch.calls]
    assert fetched and all("youtube.com" not in url for url in fetched)
    prompts = [call.request.url.params.get("prompt") for call in fetch.calls if call.request.url.params.get("prompt")]
    assert prompts and all("VERDICT:" in p and len(p) <= 2000 for p in prompts)


@respx.mock
def test_opinions_only_produce_zero_notes():
    search, _ = mock_keenable()
    opinions = [TranscriptSegment(text="I think my opponent has no vision.", start=0, duration=3)]
    with make_client(FakeTranscripts(opinions)) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 200
    assert response.json() == {"video_id": "dQw4w9WgXcQ", "status": "completed", "notes_count": 0, "notes": []}
    assert not search.called


def test_no_captions_returns_422():
    with make_client(FakeTranscripts(NoCaptionsError("No English captions"))) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 422
    assert response.json()["error"] == "NO_CAPTIONS_AVAILABLE"


@pytest.mark.parametrize("payload", [{"video_id": "short"}, {"video_id": "dQw4w9WgXcQ", "language": "fr"}])
def test_invalid_requests_return_400(payload):
    with make_client(FakeTranscripts([])) as client:
        response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_REQUEST"


def test_report_is_accepted():
    with make_client(FakeTranscripts([])) as client:
        response = client.post(
            "/api/v1/report", json={"video_id": "dQw4w9WgXcQ", "note_id": "note_001", "reason": "DEAD_LINK"}
        )
    assert response.status_code == 202 and response.json() == {"status": "received"}


def test_unconfigured_backend_returns_503():
    with TestClient(create_app(Settings(keenable_api_key=""))) as client:
        assert client.get("/healthz").json() == {"status": "ok", "configured": False}
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 503 and response.json()["error"] == "NOT_CONFIGURED"


def test_cors_allows_extension_origin():
    with make_client(FakeTranscripts([])) as client:
        origin = "chrome-extension://" + "a" * 32
        response = client.options(
            "/api/v1/analyze", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
        )
    assert response.headers.get("access-control-allow-origin") == origin


def test_client_captions_skip_youtube():
    captions = [
        {"text": "[Music]", "start": 0.0, "duration": 1.0},
        {"text": "I think we should all be kinder to each other.", "start": 1.0, "duration": 3.0},
    ]
    with make_client(FakeTranscripts(NoCaptionsError("server must not fetch"))) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "segments": captions})
    assert response.status_code == 200
    assert response.json()["notes_count"] == 0


def test_empty_client_captions_return_422():
    with make_client(FakeTranscripts([])) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "segments": []})
    assert response.status_code == 422
    assert response.json()["error"] == "NO_CAPTIONS_AVAILABLE"


@respx.mock
def test_publish_date_is_given_to_keenable(segments):
    _, fetch = mock_keenable()
    with make_client(FakeTranscripts(segments)) as client:
        body = {"video_id": "dQw4w9WgXcQ", "published_at": "2023-05-01"}
        assert client.post("/api/v1/analyze", json=body).status_code == 200
        bad = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "published_at": "yesterday"})
    assert bad.status_code == 400
    prompts = [call.request.url.params.get("prompt") for call in fetch.calls if call.request.url.params.get("prompt")]
    assert prompts and all("Video date: 2023-05-01" in p for p in prompts)


@respx.mock
def test_abstaining_sources_cost_a_single_fetch():
    search, fetch = mock_keenable()
    lines = [
        TranscriptSegment(
            text="Last year unemployment rose to 9 percent across the whole country.", start=0, duration=5
        )
    ]
    with make_client(FakeTranscripts(lines)) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "language": "en"})

    assert response.status_code == 200 and response.json()["notes_count"] == 0
    assert fetch.calls and all(call.request.url.params.get("prompt") for call in fetch.calls)


@respx.mock
def test_keenable_usage_is_counted():
    usage = {"sku": "search.pro", "amount": 1, "credits": 1.5, "paid": True}
    respx.post(f"{BASE}/v1/search").mock(
        return_value=httpx.Response(200, json={"query": "q", "mode": "pro", "results": [], "usage": usage})
    )
    keenable = KeenableClient("keen_test", BASE)
    pipeline = Pipeline(Settings(keenable_api_key="keen_test"), FakeTranscripts([]), keenable)
    with TestClient(create_app(Settings(keenable_api_key="keen_test"), pipeline)) as client:
        lines = [
            {"text": "Unemployment rose to 9 percent last year across the whole country.", "start": 0, "duration": 5}
        ]
        client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "language": "en", "segments": lines})
    assert keenable.requests == 1 and keenable.credits == 1.5
