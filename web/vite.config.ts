import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" }, // MapLibre's worker is an ES module
  server: {
    // The scenario JSON Schema lives in the repository's schemas/, outside web/.
    fs: { allow: [".", "../schemas"] },
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
