from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    keenable_api_key: str = field(default_factory=lambda: os.environ.get("KEENABLE_API_KEY", ""))
    keenable_base_url: str = field(
        default_factory=lambda: os.environ.get("KEENABLE_BASE_URL", "https://api.keenable.ai").rstrip("/")
    )
    search_max_results: int = field(default_factory=lambda: _env_int("SEARCH_MAX_RESULTS", 10))
    snippet_max_length: int = field(default_factory=lambda: _env_int("SNIPPET_MAX_LENGTH", 200))
    fetch_max_chars: int = field(default_factory=lambda: _env_int("FETCH_MAX_CHARS", 20000))
    max_claims: int = field(default_factory=lambda: _env_int("MAX_CLAIMS", 30))
    concurrency: int = field(default_factory=lambda: _env_int("PIPELINE_CONCURRENCY", 4))
    max_note_words: int = field(default_factory=lambda: _env_int("MAX_NOTE_WORDS", 50))
    allowed_origins: list[str] = field(default_factory=lambda: _env_list("ALLOWED_ORIGINS", "https://www.youtube.com"))
    report_webhook_url: str | None = field(default_factory=lambda: os.environ.get("REPORT_WEBHOOK_URL") or None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
