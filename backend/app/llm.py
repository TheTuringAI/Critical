from __future__ import annotations

import json
from typing import Any, Protocol

from openai import AsyncOpenAI

from .errors import ConfigurationError, UpstreamError


class JsonLLM(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class OpenAICompatibleLLM:
    """Any OpenAI-compatible chat completions endpoint (OpenAI, Groq, OpenRouter, Together, vLLM...)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key:
            raise ConfigurationError("LLM_API_KEY is not configured.")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 - surface any provider failure uniformly
            raise UpstreamError(f"LLM request failed: {type(exc).__name__}") from exc
        content = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise UpstreamError("LLM returned invalid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}
