import type { Layer } from "@deck.gl/core";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { CITY, fakeApi, renderWithClient } from "../testing";
import { RESULT } from "../testingResults";
import { deltaColour } from "./layers";
import { comparableResults } from "./results";

let drawn: Layer[] = [];
vi.mock("../map/MapView", () => ({
  MapView: ({ layers }: { layers: Layer[] }) => {
    drawn = layers;
    return <div data-testid="map" />;
  },
}));
beforeEach(() => {
  drawn = [];
});
afterEach(() => vi.unstubAllGlobals());

const ids = () => drawn.map((l) => l.id);

async function compareWithK1() {
  fakeApi({ ...CITY, ...RESULT });
  renderWithClient(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Compare" }));
  const picker = await screen.findByRole("combobox", { name: "Compare with" });
  await within(picker).findByRole("option", { name: /Route 10 twice as often/ });
  fireEvent.change(picker, { target: { value: "k1" } });
}

describe("comparableResults", () => {
  it("offers only results compared with the baseline", () => {
    const choices = comparableResults(RESULT["GET /api/cities/toyville/results"]);

    expect(choices).toEqual([
      {
        key: "k1",
        label: "Route 10 twice as often",
        finishedAt: "2026-10-22 10:15 UTC",
        latest: true,
      },
    ]);
  });

  it("lists newest first and marks earlier runs of the same scenario", () => {
    const run = (key: string, finished_at: string) => ({
      key,
      scenario_id: "s",
      title: "S",
      finished_at,
      assignment: true,
      compared: true,
    });
    const choices = comparableResults([
      run("old", "2026-10-20T08:00:00+00:00"),
      run("new", "2026-10-23T08:00:00+00:00"),
    ]);

    expect(choices.map((c) => [c.key, c.latest])).toEqual([
      ["new", true],
      ["old", false],
    ]);
  });
});

describe("deltaColour", () => {
  it("uses the comparison report's classes: blue gains, red losses, nothing for no change", () => {
    expect(deltaColour(0)).toEqual([0, 0, 0, 0]);
    expect(deltaColour(0.0001)).toEqual([134, 182, 239, 230]);
    expect(deltaColour(0.001)).toEqual([57, 135, 229, 230]);
    expect(deltaColour(-0.003)).toEqual([163, 41, 42, 230]);
  });
});

describe("Comparing a result with the baseline", () => {
  it("shows the change map, the changed routes and labelled metrics", async () => {
    await compareWithK1();

    await waitFor(() => expect(ids()).toEqual(["zones-change", "network", "changes"]));
    const panel = await screen.findByRole("region", { name: "Comparison" });
    const headline = await within(panel).findByRole("list", { name: "Headline metrics" });
    expect(headline).toHaveTextContent("travel time per transit trip");
    expect(headline).toHaveTextContent("77.40 min → 77.39 min");
    expect(headline).toHaveTextContent("−0.0074 min");
    expect(within(headline).getAllByRole("listitem")[0]).toHaveTextContent("better");
    expect(headline).toHaveTextContent("+0.0017 pp");
    expect(within(headline).getAllByText("Simulated")).toHaveLength(2);
    const routes = await within(panel).findByRole("list", { name: "Routes changed" });
    expect(routes).toHaveTextContent("10 modified");
    expect(routes).toHaveTextContent("boardings 40 → 65");
    expect(within(routes).getByText("Assumed")).toBeInTheDocument();
    expect(within(panel).getByRole("table", { name: "Where riders moved" })).toHaveTextContent(
      "+25 boardings",
    );
    expect(screen.getByLabelText("Legend")).toHaveTextContent("Unchanged zones are not drawn");
  });

  it("switches between baseline, scenario and change", async () => {
    await compareWithK1();
    await waitFor(() => expect(ids()).toContain("zones-change"));

    fireEvent.click(screen.getByRole("radio", { name: "Baseline" }));
    await waitFor(() => expect(ids()).toEqual(["zones-accessibility", "network"]));
    fireEvent.click(screen.getByRole("radio", { name: "Scenario" }));
    await waitFor(() => expect(ids()).toEqual(["zones-accessibility", "network", "changes"]));
  });

  it("draws the lens: baseline and scenario zones on one colour scale, cut at the divider", async () => {
    await compareWithK1();
    await waitFor(() => expect(ids()).toContain("zones-change"));

    fireEvent.click(screen.getByRole("radio", { name: "Lens" }));

    await waitFor(() =>
      expect(ids()).toEqual(["zones-split-baseline", "zones-split-scenario", "network", "changes"]),
    );
    const [left, right] = drawn as unknown as { props: { clipBounds: number[] } }[];
    expect(left!.props.clipBounds[2]).toBe(right!.props.clipBounds[0]);
    expect(screen.getByText(/Baseline left of a divider/)).toBeInTheDocument();
  });

  it("plays flows frame by frame and marks partial frames", async () => {
    await compareWithK1();
    fireEvent.click(await screen.findByRole("radio", { name: "Flow playback" }));

    const playback = await screen.findByRole("region", { name: "Playback" });
    expect(playback).toHaveTextContent("08:00–08:15");
    expect(within(playback).getByRole("note")).toHaveTextContent("trips leaving home 08:00–10:00");
    await waitFor(() => expect(ids()).toContain("flows"));

    fireEvent.change(within(playback).getByRole("slider", { name: "Time" }), {
      target: { value: "2" },
    });

    expect(playback).toHaveTextContent("08:30");
    expect(within(playback).queryByRole("note")).toBeNull();
    expect(within(playback).getByText("Simulated")).toBeInTheDocument();
    const checks = screen.getByRole("region", { name: "Model checks" });
    expect(checks).toHaveTextContent("Held-out stations (15 Observed)");
    expect(checks).toHaveTextContent("0.98 Simulated× observed entries");
    expect(checks).toHaveTextContent("16 % Simulated of peak bus segments (08:30–09:30)");
    expect(checks).toHaveTextContent("15 excluded stations are not scored");
    const flows = drawn.find((l) => l.id === "flows")!;
    expect((flows.props.data as { passengers: number }[]).map((d) => d.passengers)).toEqual([55]);
  });
});
