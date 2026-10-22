import { useEffect, useState } from "react";
import { CATEGORY_META, domainOf, formatTime, isSafeHttpUrl } from "../shared/timeline";
import type { Note, ReportReason } from "../shared/types";

const REPORT_REASONS: { value: ReportReason; label: string }[] = [
  { value: "INACCURATE", label: "Inaccurate note" },
  { value: "DEAD_LINK", label: "Dead or wrong link" },
  { value: "BIASED", label: "Not neutral" },
  { value: "OTHER", label: "Other issue" },
];

type ReportState = "idle" | "choosing" | "sending" | "sent" | "failed";

interface Props {
  note: Note | null;
  onReport: (note: Note, reason: ReportReason) => Promise<boolean>;
  onSeek?: (time: number) => void;
}

/** Keeps the last note mounted while fading out so the exit transition is visible. */
export function ContextBubble({ note, onReport, onSeek }: Props) {
  const [rendered, setRendered] = useState<Note | null>(note);
  const [report, setReport] = useState<ReportState>("idle");

  useEffect(() => {
    if (note) {
      setRendered(note);
      return;
    }
    const timer = window.setTimeout(() => setRendered(null), 260);
    return () => window.clearTimeout(timer);
  }, [note]);

  useEffect(() => setReport("idle"), [rendered?.note_id]);

  if (!rendered) return null;
  const meta = CATEGORY_META[rendered.category];
  const { source } = rendered;

  const sendReport = async (reason: ReportReason) => {
    setReport("sending");
    setReport((await onReport(rendered, reason)) ? "sent" : "failed");
  };

  return (
    <div
      role="note"
      aria-live="polite"
      data-testid="vco-bubble"
      className={`vco-fade ${note ? "vco-shown" : "vco-hidden"} mt-2 rounded-lg border border-solid border-black/10 bg-white p-3 text-base text-neutral-900 shadow-sm dark:border-white/15 dark:bg-neutral-800 dark:text-neutral-100`}
    >
      <div className="flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wide ${meta.className}`}>
          {meta.label}
        </span>
        <button
          type="button"
          onClick={() => onSeek?.(rendered.start_time)}
          className="cursor-pointer border-0 bg-transparent p-0 text-xs text-neutral-500 hover:underline dark:text-neutral-400"
        >
          {formatTime(rendered.start_time)}
        </button>
        <span className="text-xs text-neutral-500 dark:text-neutral-400">Context note</span>
        <div className="relative ml-auto">
          <ReportControl state={report} onOpen={() => setReport("choosing")} onSelect={sendReport} onCancel={() => setReport("idle")} />
        </div>
      </div>

      <p className="m-0 mt-2 text-sm italic text-neutral-600 dark:text-neutral-300">“{rendered.extracted_claim}”</p>
      <p className="m-0 mt-1.5 text-base">{rendered.summary}</p>

      <div className="mt-2 rounded-md bg-neutral-100 p-2 dark:bg-neutral-900/60">
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="font-medium">{source.publisher}</span>
          <span className="rounded-sm bg-neutral-200 px-1.5 text-xs text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200">
            {domainOf(source.url)}
          </span>
          {isSafeHttpUrl(source.url) && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-sm text-blue-700 no-underline hover:underline dark:text-blue-400"
            >
              {source.title || "View source"} ↗
            </a>
          )}
        </div>
        {source.citation && (
          <p className="m-0 mt-1 text-xs text-neutral-600 dark:text-neutral-400">“{source.citation}”</p>
        )}
      </div>
    </div>
  );
}

function ReportControl(props: {
  state: ReportState;
  onOpen: () => void;
  onSelect: (reason: ReportReason) => void;
  onCancel: () => void;
}) {
  if (props.state === "sent") return <span className="text-xs text-neutral-500">Thanks, reported</span>;
  if (props.state === "sending") return <span className="text-xs text-neutral-500">Sending…</span>;
  return (
    <>
      <button
        type="button"
        aria-label="Report this note"
        title={props.state === "failed" ? "Report failed, try again" : "Report this note"}
        onClick={props.state === "choosing" ? props.onCancel : props.onOpen}
        className="flex cursor-pointer items-center gap-1 rounded-full border-0 bg-transparent px-1.5 py-0.5 text-xs text-neutral-500 hover:bg-black/5 dark:text-neutral-400 dark:hover:bg-white/10"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M5 21V4h9l.4 2H20v10h-7l-.4-2H7v7H5z" />
        </svg>
        {props.state === "failed" ? "Retry" : "Report"}
      </button>
      {props.state === "choosing" && (
        <div role="menu" className="absolute right-0 top-full z-10 mt-1 w-40 rounded-md border border-solid border-black/10 bg-white py-1 shadow-lg dark:border-white/15 dark:bg-neutral-700">
          {REPORT_REASONS.map((reason) => (
            <button
              key={reason.value}
              role="menuitem"
              type="button"
              onClick={() => props.onSelect(reason.value)}
              className="block w-full cursor-pointer border-0 bg-transparent px-3 py-1.5 text-left text-sm text-neutral-800 hover:bg-black/5 dark:text-neutral-100 dark:hover:bg-white/10"
            >
              {reason.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
