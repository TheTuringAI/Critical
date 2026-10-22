import type { Category, Note } from "./types";

export function activeNotes(notes: Note[], time: number): Note[] {
  return notes.filter((note) => time >= note.start_time && time <= note.end_time);
}

/** Most recently started note wins when claims overlap. */
export function currentNote(notes: Note[], time: number): Note | null {
  const active = activeNotes(notes, time);
  return active.length ? active.reduce((a, b) => (b.start_time > a.start_time ? b : a)) : null;
}

export function nextNote(notes: Note[], time: number): Note | null {
  return notes.filter((note) => note.start_time > time).sort((a, b) => a.start_time - b.start_time)[0] ?? null;
}

export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function isSafeHttpUrl(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

export const CATEGORY_META: Record<Category, { label: string; className: string }> = {
  SUPPORTED: {
    label: "Supported",
    className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200",
  },
  CONTRADICTED: { label: "Contradicted", className: "bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200" },
  MISSING_CONTEXT: {
    label: "Missing context",
    className: "bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200",
  },
  UNVERIFIED_DATA: {
    label: "Unverified data",
    className: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
  },
};
