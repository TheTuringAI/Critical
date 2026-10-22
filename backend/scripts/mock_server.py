"""Dev-only server returning canned notes so the extension UI can be exercised without API keys.

Usage: python scripts/mock_server.py   (serves http://localhost:8000)
Notes are spread across the first minutes of whatever video is analyzed.
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import AnalyzeRequest, AnalyzeResponse, Category, Note, ReportRequest, ReportResponse, Source

app = FastAPI(title="Video Context Overlay mock")
app.add_middleware(CORSMiddleware, allow_origin_regex=r".*", allow_methods=["*"], allow_headers=["*"])

SAMPLES = [
    (
        Category.CONTRADICTED,
        "The country experienced a 10% decline in employment last year.",
        "Bureau of Labor Statistics data shows nonfarm payroll employment increased by 2.7 million jobs (+1.8%) over "
        "that calendar year.",
        "U.S. Bureau of Labor Statistics",
        "https://www.bls.gov/news.release/empsit.nr0.htm",
        "Total nonfarm payroll employment rose by 2.7 million in 2023.",
    ),
    (
        Category.SUPPORTED,
        "Unemployment fell to 3.4 percent in January 2023.",
        "Bureau of Labor Statistics records show the unemployment rate was 3.4 percent in January 2023.",
        "U.S. Bureau of Labor Statistics",
        "https://www.bls.gov/opub/ted/2023/",
        "The unemployment rate was 3.4 percent.",
    ),
    (
        Category.MISSING_CONTEXT,
        "GDP grew 4.9 percent in the third quarter.",
        "BEA reports 4.9% annualized growth for Q3 2023; the year-over-year increase was 2.9%.",
        "U.S. Bureau of Economic Analysis",
        "https://www.bea.gov/data/gdp/gross-domestic-product",
        "Real GDP increased at an annual rate of 4.9 percent in the third quarter.",
    ),
    (
        Category.UNVERIFIED_DATA,
        "Crime in our cities has doubled since 2019.",
        "FBI national crime data does not report a city-level doubling since 2019; "
        "no official dataset matches this figure.",
        "Federal Bureau of Investigation",
        "https://cde.ucr.cjis.gov/",
        "Crime Data Explorer national estimates.",
    ),
]


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "configured": True}


@app.post("/api/v1/analyze", response_model=AnalyzeResponse)
async def analyze(body: AnalyzeRequest) -> AnalyzeResponse:
    notes = [
        Note(
            note_id=f"note_{i + 1:03d}",
            start_time=5 + i * 20,
            end_time=17 + i * 20,
            category=cat,
            extracted_claim=q,
            summary=s,
            source=Source(title=pub + " release", publisher=pub, url=url, citation=cit),
        )
        for i, (cat, q, s, pub, url, cit) in enumerate(SAMPLES)
    ]
    return AnalyzeResponse(video_id=body.video_id, notes_count=len(notes), notes=notes)


@app.post("/api/v1/report", response_model=ReportResponse, status_code=202)
async def report(body: ReportRequest) -> ReportResponse:
    print("REPORT", body.model_dump(mode="json"))
    return ReportResponse()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
