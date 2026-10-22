import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import NoCaptionsError
from app.keenable import KeenableClient
from app.main import Pipeline, create_app

from .conftest import FakeLLM, FakeTranscripts

BASE = "https://api.keenable.ai"
CITATION = "Total nonfarm payroll employment rose by 2.7 million in 2023."

CLAIMS = [
    {
        "quote": "the country lost ten percent of its jobs, a ten percent decline in employment",
        "first_segment": 2,
        "last_segment": 3,
        "search_query": "US employment change 2023 Bureau of Labor Statistics",
    },
    {
        "quote": "unemployment fell to 3.4 percent in January 2023",
        "first_segment": 5,
        "last_segment": 5,
        "search_query": "unemployment rate January 2023 BLS",
    },
    {"quote": "out of range", "first_segment": 99, "last_segment": 99, "search_query": "x"},
]
VERDICTS = {
    "ten percent of its jobs": {
        "decision": "EMIT",
        "category": "CONTRADICTED",
        "source_index": 1,
        "summary": "Bureau of Labor Statistics data shows nonfarm payroll employment increased by 2.7 million "
        "jobs in 2023. It did not decline. This third sentence should be dropped.",
        "citation": CITATION,
        "publisher": "U.S. Bureau of Labor Statistics",
        "source_title": "Employment Situation",
    },
    "3.4 percent": {
        "decision": "EMIT",
        "category": "SUPPORTED",
        "source_index": 1,
        "summary": "BLS data shows 3.4 percent.",
        "citation": "This sentence does not appear in any evidence at all.",
    },
}


def make_client(transcripts, llm) -> TestClient:
    settings = Settings(keenable_api_key="keen_test", llm_api_key="x")
    pipeline = Pipeline(settings, transcripts, KeenableClient("keen_test", BASE), llm)
    return TestClient(create_app(settings, pipeline))


def mock_keenable():
    respx.post(f"{BASE}/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "q",
                "mode": "pro",
                "results": [
                    {
                        "title": "Employment Situation Summary",
                        "url": "https://www.bls.gov/news.release/empsit.nr0.htm",
                        "description": "",
                        "snippet": "Payroll employment data.",
                    },
                    {
                        "title": "Video",
                        "url": "https://www.youtube.com/watch?v=x",
                        "description": "",
                        "snippet": "irrelevant",
                    },
                ],
            },
        )
    )
    respx.get(f"{BASE}/v1/fetch").mock(
        return_value=httpx.Response(
            200,
            json={
                "url": "https://www.bls.gov/news.release/empsit.nr0.htm",
                "content": f"Menu\n\n{CITATION} Employment trends by sector.\n\nFooter",
            },
        )
    )


@respx.mock
def test_analyze_returns_grounded_concise_notes_and_abstains_otherwise(segments):
    mock_keenable()
    llm = FakeLLM(CLAIMS, VERDICTS)
    with make_client(FakeTranscripts(segments), llm) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ", "language": "en"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["notes_count"] == 1
    note = body["notes"][0]
    assert note["note_id"] == "note_001"
    assert note["category"] == "CONTRADICTED"
    assert note["start_time"] == 28.0 and note["end_time"] == 54.0
    assert note["summary"].endswith("It did not decline.") and "third sentence" not in note["summary"]
    assert len(note["summary"].split()) <= 50
    assert note["source"]["url"] == "https://www.bls.gov/news.release/empsit.nr0.htm"
    assert note["source"]["citation"] == CITATION
    verify_prompts = [user for system, user in llm.calls if "impartial" in system]
    assert all("youtube.com" not in prompt for prompt in verify_prompts)


@respx.mock
def test_opinions_only_produce_zero_notes(segments):
    mock_keenable()
    with make_client(FakeTranscripts(segments), FakeLLM(claims=[])) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 200
    assert response.json() == {"video_id": "dQw4w9WgXcQ", "status": "completed", "notes_count": 0, "notes": []}


def test_no_captions_returns_422():
    with make_client(FakeTranscripts(NoCaptionsError("No English captions")), FakeLLM()) as client:
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 422
    assert response.json()["error"] == "NO_CAPTIONS_AVAILABLE"


@pytest.mark.parametrize("payload", [{"video_id": "short"}, {"video_id": "dQw4w9WgXcQ", "language": "fr"}])
def test_invalid_requests_return_400(payload):
    with make_client(FakeTranscripts([]), FakeLLM()) as client:
        response = client.post("/api/v1/analyze", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_REQUEST"


def test_report_is_accepted():
    with make_client(FakeTranscripts([]), FakeLLM()) as client:
        response = client.post(
            "/api/v1/report", json={"video_id": "dQw4w9WgXcQ", "note_id": "note_001", "reason": "DEAD_LINK"}
        )
    assert response.status_code == 202 and response.json() == {"status": "received"}


def test_unconfigured_backend_returns_503():
    with TestClient(create_app(Settings(keenable_api_key="", llm_api_key=""))) as client:
        assert client.get("/healthz").json() == {"status": "ok", "configured": False}
        response = client.post("/api/v1/analyze", json={"video_id": "dQw4w9WgXcQ"})
    assert response.status_code == 503 and response.json()["error"] == "NOT_CONFIGURED"


def test_cors_allows_extension_origin():
    with make_client(FakeTranscripts([]), FakeLLM()) as client:
        origin = "chrome-extension://" + "a" * 32
        response = client.options(
            "/api/v1/analyze", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
        )
    assert response.headers.get("access-control-allow-origin") == origin
