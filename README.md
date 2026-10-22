# Video Context Overlay

Open-source, privacy-first context notes for English YouTube videos — inspired by Community Notes, built for video.

A Manifest V3 Chrome extension adds an **"Add Context & Fact-Check"** button under the YouTube player. On click, a
stateless FastAPI service pulls the video's English captions, picks out *verifiable* factual claims with deterministic
rules, then asks the [Keenable](https://keenable.ai) search & fetch API both for evidence and for the short verdict
summary. **Only a Keenable API key is needed — no LLM key.** It returns short, neutral, source-linked notes. The extension shows each note in a **Context Bubble** while the matching part of the video plays.

```
extension/  Chrome extension (TypeScript, React, Tailwind, Vite)
backend/    Stateless verification API (Python, FastAPI)
```

## How it works

1. **Transcript** – the extension reads the English captions in the user's browser (manual preferred, auto-generated
   as fallback) and sends them with the request, so the server never contacts YouTube (YouTube blocks most
   cloud/server IPs). Only when `segments` is omitted does the server fall back to `youtube-transcript-api`.
   No captions → HTTP 422 `NO_CAPTIONS_AVAILABLE`.
2. **Claim extraction (rules, no LLM)** – captions are merged into sentences (or ~25-word windows for unpunctuated
   auto-captions). A sentence becomes a claim only if it contains a concrete anchor — a figure, percentage, amount,
   year, law/bill, or attribution ("according to…") — or a checkable subject from the topic lexicon (`_TOPIC_TERMS`
   in `claims.py`: economy, taxes, health, crime, immigration, climate, elections, war, education, society) next to a
   change, comparison or superlative ("violent crime rose", "the largest tax cut") — and no opinion/speculation
   marker ("I think", "should", questions…). The best non-overlapping candidates (`MAX_CLAIMS`, default 30) keep
   their exact timestamps. Search queries put figures, subjects and names first and drop conversational filler.
3. **Evidence (Keenable search)** – `POST /v1/search` with `max_results=10`, `snippet_max_length=200` (Keenable's
   minimum is 180); social/video sites are dropped, institutional domains (`.gov`, `.edu`, `.int`, statistical
   agencies…) ranked first. Only institutional domains and an allowlist of established newsrooms, fact-checkers, encyclopedias and non-partisan research bodies are ever cited (`REPUTABLE_DOMAINS` in `verification.py`); pages titled as transcripts are skipped. The extension sends the video's publish date (`published_at`), which is given to Keenable and used to drop evidence about later years, or (for supported/contradicted verdicts) figures more than two years older than the video unless the claim itself names a year.
4. **Verdict & summary (Keenable fetch with `prompt`)** – for up to 3 top sources, `GET /v1/fetch?url=…&prompt=…`
   asks Keenable to read the page and reply `VERDICT` (`SUPPORTED`, `CONTRADICTED`, `MISSING_CONTEXT`,
   `UNVERIFIED_DATA` or `ABSTAIN`), a ≤40-word neutral `SUMMARY`, a verbatim `QUOTE` and the `PUBLISHER`.
   The prompted fetch comes first; the plain page is fetched only when it yields a verdict (Keenable bills per
   request, so an abstaining source costs one fetch, not two). The server then enforces the rules itself, dropping
   the note unless:
   - the quote really appears in the page (checked against a plain fetch of the same URL);
   - the summary shares a figure or key terms with the claim, and is not a "page doesn't say" non-answer;
   - the quote is not just the speaker's own words (transcripts of the same video are not evidence);
   - the summary is cut to at most 2 sentences / `MAX_NOTE_WORDS` (default 50) words.
   - the note is useful enough (`MIN_NOTE_USEFULNESS`, default 3, on a 0–7 scale; 4 keeps only firm, figure-backed notes): +2 for a firm verdict
     (supported / contradicted / missing context), +1 per key word shared with the claim (max 3), +1 if the summary
     gives a figure, +1 for an institutional source; −2 for a "this page has no data" answer without a figure
     (−1 with one), −1 if the claim's subject (e.g. "insulin") is absent from the evidence.
5. Notes are returned in-memory. Nothing (transcripts, results, users) is stored server-side; the extension caches
   results per video in `chrome.storage.session`, which is cleared when the browser closes.

## Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env    # set KEENABLE_API_KEY
set -a && source .env && set +a
uvicorn app.main:app --port 8000
```

See `.env.example` for all settings. To try the real pipeline from the command line:
`PYTHONPATH=. python scripts/live_check.py <video_id> [...]` prints the extracted claims and resulting notes.

| Endpoint | Description |
| --- | --- |
| `POST /api/v1/analyze` | `{"video_id": "dQw4w9WgXcQ", "language": "en", "segments"?: [{"text", "start", "duration"}]}` → `{video_id, status, notes_count, notes[]}` |
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
  content scripts). On "Add Context" it loads the English `fmt=json3` caption file in the browser (directly, or by
  letting the player download it when YouTube requires its anti-bot token) and keeps it in tab memory only.
- `content/index.tsx` follows YouTube SPA navigation (`yt-navigate-finish`) and mounts the UI in a shadow root between
  the player and the title, so YouTube's CSS and Tailwind don't interfere.
- The bubble follows `timeupdate`/`seeked` on the `<video>` element, fades in/out, adapts to YouTube's `html[dark]`
  theme, and offers a *Report* menu.
- All network calls go through the background service worker; only the video ID is ever sent.
