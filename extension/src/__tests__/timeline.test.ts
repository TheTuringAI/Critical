import { describe, expect, it } from "vitest";
import { currentNote, domainOf, formatTime, isSafeHttpUrl, nextNote } from "../shared/timeline";
import type { Note } from "../shared/types";

export const makeNote = (id: string, start: number, end: number, extra: Partial<Note> = {}): Note => ({
  note_id: id,
  start_time: start,
  end_time: end,
  category: "CONTRADICTED",
  extracted_claim: "The country experienced a 10% decline in employment last year.",
  summary: "Bureau of Labor Statistics data shows nonfarm payroll employment increased by 2.7 million jobs.",
  source: {
    title: "Employment Situation Summary",
    publisher: "U.S. Bureau of Labor Statistics",
    url: "https://www.bls.gov/news.release/empsit.nr0.htm",
    citation: "Total nonfarm payroll employment rose by 2.7 million in 2023.",
  },
  ...extra,
});

describe("timeline", () => {
  const notes = [makeNote("a", 10, 20), makeNote("b", 15, 30), makeNote("c", 60, 70)];

  it("shows the note whose window contains the current time, preferring the latest start", () => {
    expect(currentNote(notes, 5)).toBeNull();
    expect(currentNote(notes, 12)?.note_id).toBe("a");
    expect(currentNote(notes, 18)?.note_id).toBe("b");
    expect(currentNote(notes, 30)?.note_id).toBe("b");
    expect(currentNote(notes, 31)).toBeNull();
  });

  it("finds the next upcoming note", () => {
    expect(nextNote(notes, 31)?.note_id).toBe("c");
    expect(nextNote(notes, 80)).toBeNull();
  });

  it("formats times and domains", () => {
    expect(formatTime(84)).toBe("1:24");
    expect(formatTime(3725)).toBe("1:02:05");
    expect(domainOf("https://www.bls.gov/x")).toBe("bls.gov");
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("https://bls.gov")).toBe(true);
  });
});
