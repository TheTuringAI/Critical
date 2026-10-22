# Video Context Overlay

Open-source, privacy-first context notes for English YouTube videos — inspired by Community Notes, built for video.

A Manifest V3 Chrome extension adds an **"Add Context & Fact-Check"** button under the YouTube player. On click, a
stateless FastAPI service pulls the video's English captions, extracts *verifiable* factual claims with an LLM,
retrieves evidence through the [Keenable](https://keenable.ai) search & fetch API, and returns short, neutral,
source-linked notes. The extension shows each note in a **Context Bubble** while the matching part of the video plays.

```
extension/  Chrome extension (TypeScript, React, Tailwind, Vite)
backend/    Stateless verification API (Python, FastAPI)
```

## How it works

1. **Transcript** – `youtube-transcript-api` (manual English captions preferred, auto-generated as fallback).
   No captions → HTTP 422 `NO_CAPTIONS_AVAILABLE`.
2. **Claim extraction** – the transcript is split into ~3-minute overlapping windows; the LLM returns only checkable
   claims (figures, dates, laws, attributed quotes) with segment indices, mapped back to exact timestamps.
   Opinions, predictions and value judgments are ignored.
3. **Evidence (Keenable)** – `POST /v1/search` with `max_results=3`, `snippet_max_length=200`; social/video sites are
   dropped, institutional domains (`.gov`, `.edu`, `.int`, statistical agencies…) ranked first; the top
   institutional pages are scraped via `GET /v1/fetch` and reduced to the paragraphs/table rows that mention the
   claim's keywords or figures.
4. **Verdict** – the LLM either abstains or picks `SUPPORTED`, `CONTRADICTED`, `MISSING_CONTEXT` or
   `UNVERIFIED_DATA` using only that evidence. The server then enforces the rules itself:
   - the cited excerpt must actually appear in the retrieved evidence, otherwise **no note**;
   - the summary is cut to at most 2 sentences / `MAX_NOTE_WORDS` (default 50) words;
   - any malformed answer, unknown category or invalid source → **no note** (abstention by default).
5. Notes are returned in-memory. Nothing (transcripts, results, users) is stored server-side; the extension caches
   results per video in `chrome.storage.session`, which is cleared when the browser closes.

## Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env    # set KEENABLE_API_KEY and LLM_API_KEY
set -a && source .env && set +a
uvicorn app.main:app --port 8000
```

Any OpenAI-compatible chat endpoint works for the LLM (`LLM_BASE_URL`, `LLM_MODEL`; default `gpt-4o-mini`).
See `.env.example` for all settings.

| Endpoint | Description |
| --- | --- |
| `POST /api/v1/analyze` | `{"video_id": "dQw4w9WgXcQ", "language": "en"}` → `{video_id, status, notes_count, notes[]}` |
| `POST /api/v1/report` | `{"video_id", "note_id", "reason": "INACCURATE"\|"DEAD_LINK"\|"BIASED"\|"OTHER", "comment"?, "note"?}` → 202. Logged, optionally forwarded to `REPORT_WEBHOOK_URL`. |
| `GET /healthz` | `{"status": "ok", "configured": bool}` |

Errors use `{"error": CODE, "message": ...}`: `INVALID_REQUEST` (400), `VIDEO_UNAVAILABLE` (404),
`NO_CAPTIONS_AVAILABLE` (422), `UPSTREAM_ERROR` (502), `NOT_CONFIGURED` (503).

Tests and lint: `pytest` and `ruff check . && ruff format --check .`

**No keys yet?** `PYTHONPATH=. python scripts/mock_server.py` serves canned notes on port 8000 so the extension UI
can be tried on any video.

## Extension

```bash
cd extension
npm install
npm run build      # outputs extension/dist
npm test
```

Load it via `chrome://extensions` → *Developer mode* → *Load unpacked* → `extension/dist`.
The server URL defaults to `http://localhost:8000`; change it from the extension's options page (click the toolbar
icon). Custom servers are granted host access at runtime via optional host permissions.

Implementation notes:
- `page-bridge.ts` runs in the page's MAIN world to read the player's caption track list (not visible to isolated
  content scripts) and relays only `videoId` + "has English captions".
- `content/index.tsx` follows YouTube SPA navigation (`yt-navigate-finish`) and mounts the UI in a shadow root between
  the player and the title, so YouTube's CSS and Tailwind don't interfere.
- The bubble follows `timeupdate`/`seeked` on the `<video>` element, fades in/out, adapts to YouTube's `html[dark]`
  theme, and offers a *Report* menu.
- All network calls go through the background service worker; only the video ID is ever sent.
