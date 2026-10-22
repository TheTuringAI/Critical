import json

import httpx
import pytest
import respx

from app.errors import ConfigurationError
from app.keenable import KeenableClient

BASE = "https://api.keenable.ai"


@pytest.mark.asyncio
@respx.mock
async def test_search_sends_concise_params_and_api_key():
    route = respx.post(f"{BASE}/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "q",
                "mode": "pro",
                "results": [
                    {"title": "GDP", "url": "https://www.bea.gov/gdp", "description": "", "snippet": "x" * 500},
                    {"title": "no url", "description": ""},
                ],
            },
        )
    )
    client = KeenableClient("keen_test", BASE)
    hits = await client.search_claims("US GDP Q3 2023 BEA", max_results=3, snippet_max_length=200)
    await client.aclose()

    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "keen_test"
    assert json.loads(request.content) == {"query": "US GDP Q3 2023 BEA", "max_results": 3, "snippet_max_length": 200}
    assert len(hits) == 1 and len(hits[0].snippet) == 200


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_markdown_or_none_on_dead_link():
    respx.get(f"{BASE}/v1/fetch", params={"url": "https://ok.gov/a"}).mock(
        return_value=httpx.Response(200, json={"url": "https://ok.gov/a", "content": "# Title"})
    )
    respx.get(f"{BASE}/v1/fetch", params={"url": "https://dead.gov/a"}).mock(
        return_value=httpx.Response(404, json={"error": "Not found"})
    )
    client = KeenableClient("keen_test", BASE)
    assert await client.fetch_source_markdown("https://ok.gov/a") == "# Title"
    assert await client.fetch_source_markdown("https://dead.gov/a") is None
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_invalid_key_raises_configuration_error():
    respx.post(f"{BASE}/v1/search").mock(return_value=httpx.Response(401, json={"error": "Missing authentication"}))
    client = KeenableClient("bad", BASE)
    with pytest.raises(ConfigurationError):
        await client.search_claims("q")
    await client.aclose()


def test_missing_key_raises():
    with pytest.raises(ConfigurationError):
        KeenableClient("")
