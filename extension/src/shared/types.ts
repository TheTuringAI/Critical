export type Category = "SUPPORTED" | "CONTRADICTED" | "MISSING_CONTEXT" | "UNVERIFIED_DATA";

export interface NoteSource {
  title: string;
  publisher: string;
  url: string;
  citation: string;
}

export interface Note {
  note_id: string;
  start_time: number;
  end_time: number;
  category: Category;
  extracted_claim: string;
  summary: string;
  source: NoteSource;
}

export interface AnalyzeResponse {
  video_id: string;
  status: string;
  notes_count: number;
  notes: Note[];
}

export type ReportReason = "INACCURATE" | "DEAD_LINK" | "BIASED" | "OTHER";

export interface ApiError {
  error: string;
  message: string;
}

export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export type ExtensionMessage =
  | { type: "ANALYZE"; videoId: string }
  | { type: "REPORT"; videoId: string; note: Note; reason: ReportReason; comment?: string };

export interface CaptionInfo {
  videoId: string | null;
  hasEnglish: boolean;
  known: boolean;
}
