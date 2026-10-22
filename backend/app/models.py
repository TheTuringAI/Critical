from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"


class Category(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    UNVERIFIED_DATA = "UNVERIFIED_DATA"


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


class Claim(BaseModel):
    claim_id: str
    quote: str
    start_time: float
    end_time: float
    search_query: str


class SearchHit(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""
    published_at: str | None = None


class Source(BaseModel):
    title: str
    publisher: str
    url: str
    citation: str


class Note(BaseModel):
    note_id: str
    start_time: float
    end_time: float
    category: Category
    extracted_claim: str
    summary: str
    source: Source


class CaptionLine(BaseModel):
    text: str = Field(max_length=1000)
    start: float = Field(ge=0)
    duration: float = Field(ge=0, le=600)


class AnalyzeRequest(BaseModel):
    video_id: str = Field(pattern=VIDEO_ID_PATTERN)
    language: str = "en"
    # Captions read by the extension in the user's browser; the server only downloads them itself when absent.
    segments: list[CaptionLine] | None = Field(default=None, max_length=20000)
    published_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("language")
    @classmethod
    def english_only(cls, value: str) -> str:
        if value.lower().split("-")[0] != "en":
            raise ValueError("Only English ('en') is supported")
        return "en"


class AnalyzeResponse(BaseModel):
    video_id: str
    status: str = "completed"
    notes_count: int
    notes: list[Note]


class ReportReason(StrEnum):
    INACCURATE = "INACCURATE"
    DEAD_LINK = "DEAD_LINK"
    BIASED = "BIASED"
    OTHER = "OTHER"


class ReportRequest(BaseModel):
    video_id: str = Field(pattern=VIDEO_ID_PATTERN)
    note_id: str = Field(max_length=64)
    reason: ReportReason
    comment: str | None = Field(default=None, max_length=500)
    note: Note | None = None


class ReportResponse(BaseModel):
    status: str = "received"


class ApiErrorBody(BaseModel):
    error: str
    message: str
