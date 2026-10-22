export interface CaptionSegment {
  text: string;
  start: number;
  duration: number;
}

export interface Json3Captions {
  events?: { tStartMs?: number; dDurationMs?: number; segs?: { utf8?: string }[] }[];
}

/** Converts YouTube's `fmt=json3` timed-text payload into transcript lines (seconds). */
export function json3ToSegments(data: Json3Captions): CaptionSegment[] {
  return (data.events ?? []).flatMap((event) => {
    const text = (event.segs ?? [])
      .map((seg) => seg.utf8 ?? "")
      .join("")
      .replace(/\s+/g, " ")
      .trim();
    if (!text || event.tStartMs == null) return [];
    return [{ text, start: event.tStartMs / 1000, duration: Math.min(600, (event.dDurationMs ?? 0) / 1000) }];
  });
}

export interface CaptionTrack {
  languageCode?: string;
  kind?: string;
  baseUrl?: string;
}

/** Prefers human-made English captions over auto-generated ("asr") ones. */
export function pickEnglishTrack(tracks: CaptionTrack[]): CaptionTrack | undefined {
  const english = tracks.filter((track) => (track.languageCode ?? "").toLowerCase().startsWith("en"));
  return english.find((track) => track.kind !== "asr") ?? english[0];
}
