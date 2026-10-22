import { describe, expect, it } from "vitest";
import { json3ToSegments, pickEnglishTrack } from "../shared/captions";

describe("json3ToSegments", () => {
  it("joins word segments, converts ms to seconds and skips line breaks", () => {
    const segments = json3ToSegments({
      events: [
        { tStartMs: 49300, dDurationMs: 4400, segs: [{ utf8: "that the amount" }, { utf8: " of people" }] },
        { tStartMs: 50800, dDurationMs: 10, segs: [{ utf8: "\n" }] },
        { tStartMs: 50800, dDurationMs: 2900, segs: [{ utf8: "dying from diabetes" }] },
        { dDurationMs: 100, segs: [{ utf8: "no start" }] },
      ],
    });
    expect(segments).toEqual([
      { text: "that the amount of people", start: 49.3, duration: 4.4 },
      { text: "dying from diabetes", start: 50.8, duration: 2.9 },
    ]);
  });
});

describe("pickEnglishTrack", () => {
  it("prefers manual English captions over auto-generated ones", () => {
    const tracks = [
      { languageCode: "en", kind: "asr", baseUrl: "a" },
      { languageCode: "pt", baseUrl: "b" },
      { languageCode: "en-GB", baseUrl: "c" },
    ];
    expect(pickEnglishTrack(tracks)?.baseUrl).toBe("c");
    expect(pickEnglishTrack(tracks.slice(0, 2))?.baseUrl).toBe("a");
    expect(pickEnglishTrack([{ languageCode: "fr" }])).toBeUndefined();
  });
});
