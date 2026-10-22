import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// Content scripts cannot be ES modules, so each is bundled as a self-contained IIFE.
const entry = process.env.VCO_ENTRY ?? "content";
const entries: Record<string, string> = {
  content: "src/content/index.tsx",
  "page-bridge": "src/content/page-bridge.ts",
};

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: { entry: resolve(__dirname, entries[entry]), formats: ["iife"], name: "vco_" + entry.replace("-", "_"), fileName: () => `${entry}.js` },
  },
});
