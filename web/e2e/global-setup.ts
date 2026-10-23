// Before the browser tests: build Toyville from the test fixtures (demand and assignment
// included, ~10 s) and empty the tests' Redis database.

import { execFileSync } from "node:child_process";

import { ROOT, WORK, withGlacies } from "./env";

export default function globalSetup() {
  const run = (args: string[]) =>
    execFileSync("uv", ["run", ...args], { cwd: ROOT, env: withGlacies(), stdio: "inherit" });
  run(["python", "-m", "tests.e2e_city", WORK]);
  run([
    "python",
    "-c",
    "import os, redis; redis.Redis.from_url(os.environ['GLACIES_REDIS_URL']).flushdb()",
  ]);
}
