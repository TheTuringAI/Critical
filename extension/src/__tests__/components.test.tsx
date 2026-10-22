import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ContextBubble } from "../content/ContextBubble";
import { NO_CAPTIONS_MESSAGE, OverlayApp } from "../content/OverlayApp";
import type { CaptionInfo, ExtensionMessage, Result } from "../shared/types";
import { makeNote } from "./timeline.test";

afterEach(cleanup);

describe("ContextBubble", () => {
  it("renders badge, quote, summary and a safe source link", () => {
    render(<ContextBubble note={makeNote("n1", 84, 98.5)} onReport={async () => true} />);
    expect(screen.getByText("Contradicted")).toBeTruthy();
    expect(screen.getByText(/10% decline/)).toBeTruthy();
    expect(screen.getByText("bls.gov")).toBeTruthy();
    const link = screen.getByRole("link") as HTMLAnchorElement;
    expect(link.href).toBe("https://www.bls.gov/news.release/empsit.nr0.htm");
    expect(link.rel).toContain("noopener");
  });

  it("does not render javascript: links", () => {
    const note = makeNote("n1", 0, 5);
    note.source.url = "javascript:alert(1)";
    render(<ContextBubble note={note} onReport={async () => true} />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("reports a note with the chosen reason", async () => {
    const onReport = vi.fn(async () => true);
    render(<ContextBubble note={makeNote("n1", 0, 5)} onReport={onReport} />);
    fireEvent.click(screen.getByLabelText("Report this note"));
    await act(async () => fireEvent.click(screen.getByText("Dead or wrong link")));
    expect(onReport).toHaveBeenCalledWith(expect.objectContaining({ note_id: "n1" }), "DEAD_LINK");
    expect(screen.getByText("Thanks, reported")).toBeTruthy();
  });
});

describe("OverlayApp", () => {
  const video = document.createElement("video");

  const setup = (captions: CaptionInfo, result: Result<unknown>) => {
    const send = vi.fn(async (_m: ExtensionMessage) => result) as unknown as <T>(m: ExtensionMessage) => Promise<Result<T>>;
    render(<OverlayApp videoId="dQw4w9WgXcQ" getCaptions={async () => captions} getVideo={() => video} send={send} />);
    return send;
  };

  it("shows the disabled status when there are no English captions", async () => {
    setup({ videoId: "dQw4w9WgXcQ", hasEnglish: false, known: true }, { ok: true, data: {} });
    expect((await screen.findByTestId("vco-no-captions")).textContent).toBe(NO_CAPTIONS_MESSAGE);
    expect(screen.queryByText("Add Context & Fact-Check")).toBeNull();
  });

  it("analyzes on click and syncs the bubble to video time", async () => {
    const notes = [makeNote("note_001", 84, 98.5)];
    const send = setup(
      { videoId: "dQw4w9WgXcQ", hasEnglish: true, known: true },
      { ok: true, data: { video_id: "dQw4w9WgXcQ", status: "completed", notes_count: 1, notes } },
    );
    const button = await screen.findByText("Add Context & Fact-Check");
    await act(async () => fireEvent.click(button));
    expect(send).toHaveBeenCalledWith({ type: "ANALYZE", videoId: "dQw4w9WgXcQ" });
    expect(screen.getByText("1 context note:")).toBeTruthy();
    expect(screen.queryByTestId("vco-bubble")).toBeNull();

    await act(async () => {
      video.currentTime = 90;
      video.dispatchEvent(new Event("timeupdate"));
    });
    expect(screen.getByTestId("vco-bubble").className).toContain("vco-shown");

    await act(async () => {
      video.currentTime = 120;
      video.dispatchEvent(new Event("timeupdate"));
    });
    expect(screen.getByTestId("vco-bubble").className).toContain("vco-hidden");
  });

  it("surfaces backend errors with a retry", async () => {
    setup(
      { videoId: "dQw4w9WgXcQ", hasEnglish: true, known: true },
      { ok: false, error: { error: "NETWORK_ERROR", message: "Could not reach the verification server." } },
    );
    const button = await screen.findByText("Add Context & Fact-Check");
    await act(async () => fireEvent.click(button));
    expect(screen.getByText("Could not reach the verification server.")).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
  });
});
