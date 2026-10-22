// Runs in the page's MAIN world so it can read YouTube's player response (caption track list),
// which is invisible to the isolated content script. It only relays non-personal metadata.
interface CaptionTrack {
  languageCode?: string;
}
interface PlayerResponse {
  videoDetails?: { videoId?: string };
  captions?: { playerCaptionsTracklistRenderer?: { captionTracks?: CaptionTrack[] } };
}
type PlayerElement = HTMLElement & { getPlayerResponse?: () => PlayerResponse | undefined };

function readPlayerResponse(): PlayerResponse | undefined {
  const player = document.getElementById("movie_player") as PlayerElement | null;
  return player?.getPlayerResponse?.() ?? (window as unknown as { ytInitialPlayerResponse?: PlayerResponse }).ytInitialPlayerResponse;
}

function publish(): void {
  const response = readPlayerResponse();
  const tracks = response?.captions?.playerCaptionsTracklistRenderer?.captionTracks ?? [];
  window.postMessage(
    {
      source: "vco-bridge",
      type: "CAPTIONS",
      videoId: response?.videoDetails?.videoId ?? null,
      hasEnglish: tracks.some((track) => (track.languageCode ?? "").toLowerCase().startsWith("en")),
      known: Boolean(response),
    },
    window.location.origin,
  );
}

window.addEventListener("message", (event) => {
  if (event.source === window && event.data?.source === "vco-content" && event.data.type === "GET_CAPTIONS") publish();
});
document.addEventListener("yt-player-updated", publish);
document.addEventListener("yt-navigate-finish", publish);
