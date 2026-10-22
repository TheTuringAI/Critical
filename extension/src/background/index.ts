import type { CaptionSegment } from "../shared/captions";
import { getBackendUrl } from "../shared/settings";
import type { AnalyzeResponse, ApiError, ExtensionMessage, Note, ReportReason, Result } from "../shared/types";

const CACHE_PREFIX = "notes:";

chrome.runtime.onInstalled.addListener(() => {
  chrome.action.disable();
  chrome.declarativeContent.onPageChanged.removeRules(undefined, () => {
    chrome.declarativeContent.onPageChanged.addRules([
      {
        conditions: [
          new chrome.declarativeContent.PageStateMatcher({
            pageUrl: { hostEquals: "www.youtube.com", pathEquals: "/watch", schemes: ["https"] },
          }),
        ],
        actions: [new chrome.declarativeContent.ShowAction()],
      },
    ]);
  });
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());

chrome.runtime.onMessage.addListener((message: ExtensionMessage, _sender, sendResponse) => {
  if (message.type === "ANALYZE") {
    analyze(message.videoId, message.segments, message.published).then(sendResponse);
    return true;
  }
  if (message.type === "REPORT") {
    report(message.videoId, message.note, message.reason, message.comment).then(sendResponse);
    return true;
  }
  return false;
});

async function analyze(
  videoId: string,
  segments: CaptionSegment[] | null,
  published: string | null,
): Promise<Result<AnalyzeResponse>> {
  // chrome.storage.session lives in memory only and is cleared when the browser closes.
  const key = CACHE_PREFIX + videoId;
  const cached = (await chrome.storage.session.get(key))[key] as AnalyzeResponse | undefined;
  if (cached) return { ok: true, data: cached };

  // Captions read in the browser are sent along; without them the server fetches them itself.
  // The publish date stops sources from later years being used to check what was said at the time.
  const body: Record<string, unknown> = { video_id: videoId, language: "en" };
  if (segments?.length) body.segments = segments;
  if (published) body.published_at = published;
  const result = await postJson<AnalyzeResponse>("/api/v1/analyze", body);
  if (result.ok) await chrome.storage.session.set({ [key]: result.data });
  return result;
}

async function report(videoId: string, note: Note, reason: ReportReason, comment?: string): Promise<Result<unknown>> {
  return postJson("/api/v1/report", { video_id: videoId, note_id: note.note_id, reason, comment, note });
}

async function postJson<T>(path: string, body: unknown): Promise<Result<T>> {
  const base = await getBackendUrl();
  try {
    const response = await fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const error: ApiError =
        payload && typeof payload.error === "string"
          ? payload
          : { error: "HTTP_" + response.status, message: `Server responded with HTTP ${response.status}.` };
      return { ok: false, error };
    }
    return { ok: true, data: payload as T };
  } catch {
    return {
      ok: false,
      error: { error: "NETWORK_ERROR", message: `Could not reach the verification server at ${base}.` },
    };
  }
}
