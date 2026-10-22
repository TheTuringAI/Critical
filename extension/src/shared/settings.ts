export const DEFAULT_BACKEND_URL = "http://localhost:8000";

export async function getBackendUrl(): Promise<string> {
  const { backendUrl } = await chrome.storage.sync.get("backendUrl");
  return (typeof backendUrl === "string" && backendUrl.trim() ? backendUrl.trim() : DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

export async function setBackendUrl(url: string): Promise<void> {
  await chrome.storage.sync.set({ backendUrl: url.trim().replace(/\/+$/, "") });
}
