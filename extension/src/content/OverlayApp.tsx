import { useCallback, useEffect, useState } from "react";
import type { Transcript } from "../shared/captions";
import { currentNote, formatTime } from "../shared/timeline";
import type { AnalyzeResponse, CaptionInfo, ExtensionMessage, Note, ReportReason, Result } from "../shared/types";
import { ContextBubble } from "./ContextBubble";

type Status =
  | { kind: "checking" }
  | { kind: "no-captions" }
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; notes: Note[] }
  | { kind: "error"; message: string };

export const NO_CAPTIONS_MESSAGE = "No English captions available for automated fact-checking.";

interface Props {
  videoId: string;
  getCaptions: (videoId: string) => Promise<CaptionInfo>;
  getTranscript: (videoId: string) => Promise<Transcript>;
  getVideo: () => HTMLVideoElement | null;
  send: <T>(message: ExtensionMessage) => Promise<Result<T>>;
}

export function OverlayApp({ videoId, getCaptions, getTranscript, getVideo, send }: Props) {
  const [status, setStatus] = useState<Status>({ kind: "checking" });
  const [time, setTime] = useState(0);
  const dark = useYouTubeDarkTheme();

  useEffect(() => {
    let cancelled = false;
    getCaptions(videoId).then((info) => {
      if (!cancelled) setStatus(info.known && !info.hasEnglish ? { kind: "no-captions" } : { kind: "idle" });
    });
    return () => {
      cancelled = true;
    };
  }, [videoId, getCaptions]);

  const notes = status.kind === "ready" ? status.notes : null;
  useEffect(() => {
    const video = getVideo();
    if (!notes?.length || !video) return;
    const update = () => setTime(video.currentTime);
    update();
    video.addEventListener("timeupdate", update);
    video.addEventListener("seeked", update);
    return () => {
      video.removeEventListener("timeupdate", update);
      video.removeEventListener("seeked", update);
    };
  }, [notes, getVideo]);

  const analyze = async () => {
    setStatus({ kind: "loading" });
    const { segments, published } = await getTranscript(videoId);
    const result = await send<AnalyzeResponse>({ type: "ANALYZE", videoId, segments, published });
    if (result.ok) setStatus({ kind: "ready", notes: [...result.data.notes].sort((a, b) => a.start_time - b.start_time) });
    else if (result.error.error === "NO_CAPTIONS_AVAILABLE") setStatus({ kind: "no-captions" });
    else setStatus({ kind: "error", message: result.error.message });
  };

  const report = useCallback(
    async (note: Note, reason: ReportReason) => (await send({ type: "REPORT", videoId, note, reason })).ok,
    [send, videoId],
  );

  const seek = useCallback(
    (seconds: number) => {
      const video = getVideo();
      if (video) video.currentTime = seconds;
    },
    [getVideo],
  );

  return (
    <div className={dark ? "vco-dark" : ""}>
      <div className="pt-3 text-base text-neutral-900 dark:text-neutral-100">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Logo />
          <StatusLine status={status} onAnalyze={analyze} onSeek={seek} />
        </div>
        <ContextBubble note={notes ? currentNote(notes, time) : null} onReport={report} onSeek={seek} />
      </div>
    </div>
  );
}

function StatusLine({ status, onAnalyze, onSeek }: { status: Status; onAnalyze: () => void; onSeek: (t: number) => void }) {
  const muted = "text-neutral-600 dark:text-neutral-400";
  switch (status.kind) {
    case "checking":
      return <span className={muted}>Checking captions…</span>;
    case "no-captions":
      return (
        <span className={muted} data-testid="vco-no-captions">
          {NO_CAPTIONS_MESSAGE}
        </span>
      );
    case "idle":
      return <AnalyzeButton onClick={onAnalyze} label="Add Context & Fact-Check" />;
    case "loading":
      return (
        <span className={`flex items-center gap-2 ${muted}`} data-testid="vco-loading">
          <span className="vco-spinner inline-block h-3 w-3 rounded-full border-2 border-solid border-current border-t-transparent" />
          Searching &amp; verifying claims via Keenable…
        </span>
      );
    case "error":
      return (
        <>
          <span className="text-red-700 dark:text-red-400">{status.message}</span>
          <AnalyzeButton onClick={onAnalyze} label="Retry" />
        </>
      );
    case "ready":
      if (!status.notes.length)
        return <span className={muted}>No verifiable claims could be checked with confidence in this video.</span>;
      return (
        <>
          <span className={muted}>
            {status.notes.length} context {status.notes.length === 1 ? "note" : "notes"}:
          </span>
          {status.notes.map((note) => (
            <button
              key={note.note_id}
              type="button"
              onClick={() => onSeek(note.start_time)}
              title={note.extracted_claim}
              className="cursor-pointer rounded-full border-0 bg-black/5 px-2 py-0.5 text-xs text-neutral-800 hover:bg-black/10 dark:bg-white/10 dark:text-neutral-200 dark:hover:bg-white/20"
            >
              {formatTime(note.start_time)}
            </button>
          ))}
        </>
      );
  }
}

function AnalyzeButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="cursor-pointer rounded-full border-0 bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-400"
    >
      {label}
    </button>
  );
}

function Logo() {
  return (
    <span className="flex items-center gap-1 font-medium" aria-label="Video Context Overlay">
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
        <rect width="24" height="24" rx="6" fill="#2563eb" />
        <circle cx="12" cy="7" r="1.8" fill="#fff" />
        <rect x="10.5" y="10" width="3" height="9" rx="1" fill="#fff" />
      </svg>
      Context
    </span>
  );
}

function useYouTubeDarkTheme(): boolean {
  const read = () => document.documentElement.hasAttribute("dark");
  const [dark, setDark] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["dark"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}
