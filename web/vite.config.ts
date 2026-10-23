import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" }, // MapLibre's worker is an ES module
  server: {
    // The scenario JSON Schema lives in the repository's schemas/, outside web/.
    fs: { allow: [".", "../schemas"] },
    proxy: {
      // The browser tests run their own API on another port.
      "/api": process.env.GLACIES_API_URL ?? "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ runs under Playwright
  },
});
