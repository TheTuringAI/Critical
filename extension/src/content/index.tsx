import { createRoot, type Root } from "react-dom/client";
import type { CaptionInfo, ExtensionMessage, Result } from "../shared/types";
import { OverlayApp } from "./OverlayApp";
import css from "./styles.css?inline";

const HOST_ID = "vco-root";
const ANCHOR_SELECTORS = [
  "ytd-watch-flexy #below ytd-watch-metadata",
  "ytd-watch-flexy #below #above-the-fold",
  "ytd-watch-flexy #below #meta",
];

let root: Root | null = null;
let host: HTMLElement | null = null;
let currentVideoId: string | null = null;
let anchorObserver: MutationObserver | null = null;

function videoIdFromLocation(): string | null {
  if (location.pathname !== "/watch") return null;
  const id = new URLSearchParams(location.search).get("v");
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}

function findAnchor(): Element | null {
  for (const selector of ANCHOR_SELECTORS) {
    const element = document.querySelector(selector);
    if (element) return element;
  }
  return null;
}

function ensureHost(anchor: Element): void {
  if (!host) {
    host = document.createElement("div");
    host.id = HOST_ID;
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = css;
    const container = document.createElement("div");
    shadow.append(style, container);
    root = createRoot(container);
  }
  if (host.nextElementSibling !== anchor) anchor.parentElement?.insertBefore(host, anchor);
}

function getVideo(): HTMLVideoElement | null {
  return document.querySelector<HTMLVideoElement>("#movie_player video");
}

function send<T>(message: ExtensionMessage): Promise<Result<T>> {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (response?: Result<T>) => {
        if (chrome.runtime.lastError || !response) {
          resolve({ ok: false, error: { error: "EXTENSION_ERROR", message: "Extension was updated. Reload the page." } });
        } else resolve(response);
      });
    } catch {
      resolve({ ok: false, error: { error: "EXTENSION_ERROR", message: "Extension was updated. Reload the page." } });
    }
  });
}

/** Asks the MAIN-world bridge for the caption track list of the current player response. */
function getCaptions(videoId: string, timeoutMs = 8000): Promise<CaptionInfo> {
  return new Promise((resolve) => {
    const finish = (info: CaptionInfo) => {
      window.removeEventListener("message", onMessage);
      window.clearInterval(poll);
      window.clearTimeout(timer);
      resolve(info);
    };
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (event.source !== window || data?.source !== "vco-bridge" || data.type !== "CAPTIONS") return;
      if (data.known && data.videoId === videoId) finish({ videoId, hasEnglish: Boolean(data.hasEnglish), known: true });
    };
    const ask = () => window.postMessage({ source: "vco-content", type: "GET_CAPTIONS" }, location.origin);
    window.addEventListener("message", onMessage);
    const poll = window.setInterval(ask, 500);
    const timer = window.setTimeout(() => finish({ videoId, hasEnglish: false, known: false }), timeoutMs);
    ask();
  });
}

function render(): void {
  const videoId = videoIdFromLocation();
  anchorObserver?.disconnect();
  if (!videoId) {
    currentVideoId = null;
    root?.render(null);
    host?.remove();
    return;
  }
  const place = (): boolean => {
    const anchor = findAnchor();
    if (!anchor) return false;
    ensureHost(anchor);
    if (videoId !== currentVideoId) {
      currentVideoId = videoId;
      root!.render(<OverlayApp key={videoId} videoId={videoId} getCaptions={getCaptions} getVideo={getVideo} send={send} />);
    }
    return true;
  };
  if (place()) return;
  anchorObserver = new MutationObserver(() => {
    if (place()) anchorObserver?.disconnect();
  });
  anchorObserver.observe(document.body, { childList: true, subtree: true });
}

document.addEventListener("yt-navigate-finish", render);
window.addEventListener("popstate", render);
render();
