// Where the browser tests' own Toyville, API and queue live. Shared by the Playwright config,
// the global setup and the specs (which run the worker).

import path from "node:path";

export const ROOT = path.resolve(import.meta.dirname, "..", "..");
// Outside web/: the Vite dev server watches web/, and on Windows its file watcher keeps the
// runner from renaming its result folders.
export const WORK = path.join(ROOT, ".e2e"); // gitignored
export const API_PORT = 8001;
export const WEB_PORT = 5174;

export const GLACIES_ENV = {
  GLACIES_CITIES_DIR: path.join(ROOT, "tests", "fixtures", "cities"),
  GLACIES_CITY: "toyville",
  GLACIES_DATA_DIR: path.join(WORK, "data"),
  GLACIES_SCENARIOS_DIR: path.join(WORK, "scenarios"),
  // Database 15, emptied before every run, so a developer's own simulations are untouched.
  GLACIES_REDIS_URL: process.env.GLACIES_REDIS_URL ?? "redis://localhost:6379/15",
};

export const withGlacies = () => ({ ...process.env, ...GLACIES_ENV }) as Record<string, string>;
