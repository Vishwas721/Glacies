// The PRD §73 demonstration on Toyville: baseline, accessibility, a scenario, a run, before and
// after, where things changed, and passenger flows.

import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { ROOT, withGlacies } from "./env";

/** Run every queued simulation and stop: the tests need no long-lived worker. */
const runWorker = () =>
  execFileSync("uv", ["run", "glacies", "worker", "--burst"], {
    cwd: ROOT,
    env: withGlacies(),
    stdio: "inherit",
  });

test("the demo story", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));

  // 1. Load the baseline network.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Toyville" })).toBeVisible();
  await expect(page.getByText(/timetable of 2026-10-13/)).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();

  // 2. Current accessibility, labelled.
  await expect(page.getByLabel("Legend")).toContainText("Simulated");

  // 3. A scenario: route 10 twice as often.
  await page.getByRole("button", { name: "Design" }).click();
  await page.getByRole("searchbox", { name: "Find a route" }).fill("10");
  await page.getByRole("combobox", { name: "10 frequency" }).selectOption("0.5");
  await page.getByPlaceholder("my_scenario").fill("e2e_faster_10");
  await page.getByLabel("Title").fill("Route 10 twice as often");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/saved as e2e_faster_10/)).toBeVisible();

  // 4. Run it.
  await page.getByRole("button", { name: "Simulate" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("queued");
  runWorker();
  await expect(status).toContainText("completed", { timeout: 30_000 });
  await status.getByRole("button", { name: "Show results" }).click();

  // 5. Before and after, every number labelled.
  const headline = page.getByRole("list", { name: "Headline metrics" });
  await expect(headline).toContainText("waiting per transit trip");
  await expect(headline.getByText("Simulated").first()).toBeVisible();

  // 6-7. Where it changed and what changed.
  await expect(page.getByLabel("Legend")).toContainText("scenario minus baseline");
  await expect(page.getByRole("list", { name: "Routes changed" })).toContainText("10 modified");

  // Passenger flows, with the model checks beside them.
  await page.getByRole("radio", { name: "Flow playback" }).check();
  await expect(page.getByRole("region", { name: "Playback" })).toContainText("08:00");
  await expect(page.getByRole("region", { name: "Model checks" })).toBeVisible();

  expect(problems).toEqual([]);
});
