// The way in for everyone else (ADR 0024): the landing page, then the Easy view's three steps on
// Toyville, answered by the run the demo story made (the specs run in file order, one worker).

import { expect, test } from "@playwright/test";

test("landing page to an answer in the Easy view", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /What if your bus came/ })).toBeVisible();
  await expect(page.getByText("bus and metro routes")).toBeVisible();
  await page
    .getByRole("navigation", { name: "Choose a view" })
    .getByRole("link", { name: /^Easy/ })
    .click();
  await expect(page).toHaveURL(/\/easy/);

  // 1. A place, and where it reaches.
  await page.getByRole("combobox", { name: "Search a stop or station" }).fill("Stop A");
  await page.getByRole("listbox").getByRole("button", { name: "Stop A" }).click();
  await expect(page.getByText("areas within 45 minutes")).toBeVisible();
  await expect(page.getByLabel("Map key")).toContainText("Door to door");
  await page.getByRole("button", { name: /Next: ask a what-if/ }).click();

  // 2. A question already answered.
  await page.getByRole("button", { name: /Route 10 twice as often/ }).click();

  // 3. The answer, for the place and the city, labelled.
  await expect(page.getByRole("heading", { name: "For trips from Stop A" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "For the whole city" })).toBeVisible();
  await expect(page.getByText("Waiting for a bus or train")).toBeVisible();
  await expect(page.getByText("Simulated").first()).toBeVisible();

  // The theme switch and the way to the full screen.
  const html = page.locator("html");
  const before = await html.getAttribute("data-theme");
  const after = before === "dark" ? "light" : "dark";
  await page.getByRole("button", { name: `Switch to the ${after} theme` }).click();
  await expect(html).toHaveAttribute("data-theme", after);
  await page.getByRole("link", { name: "Pro view" }).click();
  await expect(page.getByRole("heading", { name: "Toyville" })).toBeVisible();

  expect(problems).toEqual([]);
});
