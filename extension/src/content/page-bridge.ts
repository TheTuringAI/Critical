// Runs in the page's MAIN world (at document_start) so it can read YouTube's player response and caption
// files, which are invisible to the isolated content script. Captions are read in the user's browser and
// kept in this tab's memory only, so the verification server never has to contact YouTube.
import { json3ToSegments, pickEnglishTrack, type CaptionSegment, type CaptionTrack, type Json3Captions } from "../shared/captions";

interface PlayerResponse {
  videoDetails?: { videoId?: string };
  captions?: { playerCaptionsTracklistRenderer?: { captionTracks?: CaptionTrack[] } };
}
type PlayerElement = HTMLElement & {
  getPlayerResponse?: () => PlayerResponse | undefined;
  loadModule?: (name: string) => void;
  unloadModule?: (name: string) => void;
  getOption?: (module: string, option: string) => { languageCode?: string } | undefined;
  setOption?: (module: string, option: string, value: unknown) => void;
};

const TIMEDTEXT = "/api/timedtext";
const captured = new Map<string, Json3Captions>();

function getPlayer(): PlayerElement | null {
  return document.getElementById("movie_player") as PlayerElement | null;
}

function readPlayerResponse(): PlayerResponse | undefined {
  return getPlayer()?.getPlayerResponse?.() ?? (window as unknown as { ytInitialPlayerResponse?: PlayerResponse }).ytInitialPlayerResponse;
}

function captionTracks(): CaptionTrack[] {
  return readPlayerResponse()?.captions?.playerCaptionsTracklistRenderer?.captionTracks ?? [];
}

/** Keeps English json3 caption files the player downloads itself (they carry YouTube's anti-bot token). */
function remember(url: string, body: string): void {
  try {
    const parsed = new URL(url, location.href);
    const lang = (parsed.searchParams.get("tlang") ?? parsed.searchParams.get("lang") ?? "").toLowerCase();
    const videoId = parsed.searchParams.get("v");
    if (!videoId || !lang.startsWith("en") || parsed.searchParams.get("fmt") !== "json3") return;
    const data = JSON.parse(body) as Json3Captions;
    if (data.events?.length) captured.set(videoId, data);
  } catch {
    // Not a caption file we can use.
  }
}

const originalFetch = window.fetch.bind(window);
window.fetch = async (...args: Parameters<typeof fetch>) => {
  const response = await originalFetch(...args);
  const input = args[0];
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (url.includes(TIMEDTEXT) && response.ok) {
    response
      .clone()
      .text()
      .then((body) => remember(url, body))
      .catch(() => undefined);
  }
  return response;
};

const originalOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, ...args: Parameters<XMLHttpRequest["open"]>) {
  const url = String(args[1]);
  if (url.includes(TIMEDTEXT)) {
    this.addEventListener("load", () => {
      if (this.status === 200 && (this.responseType === "" || this.responseType === "text")) remember(url, this.responseText);
    });
  }
  return originalOpen.apply(this, args);
} as typeof originalOpen;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchTrack(track: CaptionTrack): Promise<CaptionSegment[] | null> {
  if (!track.baseUrl) return null;
  try {
    const response = await originalFetch(track.baseUrl + "&fmt=json3", { credentials: "include" });
    const body = response.ok ? await response.text() : "";
    const segments = body ? json3ToSegments(JSON.parse(body) as Json3Captions) : [];
    return segments.length ? segments : null;
  } catch {
    return null;
  }
}

/** Newer YouTube builds reject caption URLs without a player token: let the player download the track itself. */
async function loadThroughPlayer(videoId: string, track: CaptionTrack): Promise<CaptionSegment[] | null> {
  const player = getPlayer();
  if (!player?.setOption) return null;
  const wasShowing = Boolean(player.getOption?.("captions", "track")?.languageCode);
  player.loadModule?.("captions");
  player.setOption("captions", "track", { languageCode: track.languageCode });
  for (let i = 0; i < 40 && !captured.has(videoId); i++) await sleep(250);
  if (!wasShowing) player.unloadModule?.("captions");
  const data = captured.get(videoId);
  return data ? json3ToSegments(data) : null;
}

async function loadTranscript(videoId: string): Promise<CaptionSegment[] | null> {
  if (readPlayerResponse()?.videoDetails?.videoId !== videoId) return null;
  const cached = captured.get(videoId);
  if (cached) return json3ToSegments(cached);
  const track = pickEnglishTrack(captionTracks());
  if (!track) return null;
  return (await fetchTrack(track)) ?? (await loadThroughPlayer(videoId, track));
}

function publish(): void {
  const response = readPlayerResponse();
  window.postMessage(
    {
      source: "vco-bridge",
      type: "CAPTIONS",
      videoId: response?.videoDetails?.videoId ?? null,
      hasEnglish: Boolean(pickEnglishTrack(captionTracks())),
      known: Boolean(response),
    },
    window.location.origin,
  );
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.source !== "vco-content") return;
  if (event.data.type === "GET_CAPTIONS") publish();
  if (event.data.type === "GET_TRANSCRIPT") {
    const { videoId, requestId } = event.data as { videoId: string; requestId: string };
    loadTranscript(videoId).then((segments) =>
      window.postMessage({ source: "vco-bridge", type: "TRANSCRIPT", requestId, segments }, window.location.origin),
    );
  }
});
document.addEventListener("yt-player-updated", publish);
document.addEventListener("yt-navigate-finish", publish);
