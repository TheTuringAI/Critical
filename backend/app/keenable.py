from __future__ import annotations

import asyncio
import logging

import httpx

from .errors import ConfigurationError, UpstreamError
from .models import SearchHit

logger = logging.getLogger("vco.keenable")
_RETRY_STATUS = {429, 502, 503, 504}


class KeenableClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.keenable.ai",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ):
        if not api_key:
            raise ConfigurationError("KEENABLE_API_KEY is not configured.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.retry_delay = 1.0
        self.requests = 0
        self.credits = 0.0

    def _bill(self, response: httpx.Response) -> dict:
        """Keenable bills per request (1 unit per search or fetch); the counters make the cost per video visible."""
        body = response.json()
        self.requests += 1
        self.credits += float((body.get("usage") or {}).get("credits") or 0)
        return body

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Retries once on rate limits and transient failures, which otherwise silently cost notes."""
        try:
            response = await self._client.request(method, url, **kwargs)
            if response.status_code not in _RETRY_STATUS:
                return response
        except httpx.TransportError:
            pass
        await asyncio.sleep(self.retry_delay)
        return await self._client.request(method, url, **kwargs)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search_claims(self, query: str, max_results: int = 3, snippet_max_length: int = 200) -> list[SearchHit]:
        payload = {
            "query": query,
            "max_results": max(1, min(max_results, 50)),
            # Keenable enforces a 180-char minimum snippet length.
            "snippet_max_length": max(180, snippet_max_length),
        }
        headers = {"X-API-Key": self._api_key, "Content-Type": "application/json"}
        try:
            response = await self._request("POST", f"{self._base_url}/v1/search", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Keenable search failed: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ConfigurationError("Keenable rejected the API key.")
        if response.status_code >= 400:
            raise UpstreamError(f"Keenable search returned HTTP {response.status_code}")
        hits = []
        for item in self._bill(response).get("results", [])[:max_results]:
            url = item.get("url")
            if url:
                hits.append(
                    SearchHit(
                        title=item.get("title") or "",
                        url=url,
                        snippet=(item.get("snippet") or item.get("description") or "")[:snippet_max_length],
                        published_at=item.get("published_at"),
                    )
                )
        return hits

    async def fetch_source_markdown(self, url: str, max_chars: int = 20000, prompt: str | None = None) -> str | None:
        """Clean markdown for a page, or None when it cannot be fetched (dead link, bot wall, empty page).

        With `prompt`, Keenable reads the page itself and returns only its answer to the instruction.
        """
        params: dict[str, str | int] = {"url": url, "max_chars": max_chars}
        if prompt:
            params["prompt"] = prompt[:2000]
        try:
            response = await self._request(
                "GET",
                f"{self._base_url}/v1/fetch",
                params=params,
                headers={"X-API-Key": self._api_key},
            )
        except httpx.HTTPError as exc:
            logger.info("Keenable fetch error for %s: %s", url, type(exc).__name__)
            return None
        if response.status_code == 401:
            raise ConfigurationError("Keenable rejected the API key.")
        if response.status_code >= 400:
            logger.info("Keenable fetch %s for %s: %s", response.status_code, url, response.text[:120])
            return None
        return self._bill(response).get("content") or None
