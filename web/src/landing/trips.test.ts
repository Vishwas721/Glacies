import { describe, expect, it } from "vitest";

import type { Flows } from "../api/types";
import { pageOf } from "../router";
import { clockSeconds, clockText, coreBox, trailsFromFlows } from "./trips";

const flows = {
  frame_minutes: 15,
  frames: [
    { start: "08:00", partial: true, passenger_segments: 30 },
    { start: "08:15", partial: false, passenger_segments: 40.5 },
  ],
  pairs: {
    from_stop_idx: [0, 1],
    to_stop_idx: [1, 2],
    coordinates: [
      [77.6, 12.9, 77.6, 12.91],
      [77.6, 12.91, 77.62, 12.91],
    ],
    mode: ["bus", "metro"],
  },
  frame_idx: [0, 1, 1],
  pair_idx: [0, 0, 1],
  passengers: [30, 0.5, 40],
  load_factor: [0.5, 0, 0.4],
} as unknown as Flows;

describe("morning trails", () => {
  it("draws one trail per pair and frame, leaving inside the frame", () => {
    const { trails, start, end } = trailsFromFlows(flows);
    // The 0.5-passenger row is residue: no trail.
    expect(trails.map((t) => [t.metro, t.passengers])).toEqual([
      [false, 30],
      [true, 40],
    ]);
    const [bus, metro] = trails;
    expect(bus!.timestamps[0]).toBeGreaterThanOrEqual(clockSeconds("08:00"));
    expect(bus!.timestamps[0]).toBeLessThan(clockSeconds("08:15"));
    expect(metro!.timestamps[0]).toBeGreaterThanOrEqual(clockSeconds("08:15"));
    // About 1.1 km by bus at 5 m/s, and the trails span the drawing's clock.
    expect(bus!.timestamps[1] - bus!.timestamps[0]).toBeCloseTo(1105.4 / 5, 0);
    expect(start).toBe(bus!.timestamps[0]);
    expect(end).toBe(Math.max(bus!.timestamps[1], metro!.timestamps[1]));
    expect(coreBox(trailsFromFlows(flows))).toEqual([77.6, 12.9, 77.6, 12.9]);
  });

  it("reads and writes the clock", () => {
    expect(clockSeconds("08:15")).toBe(29_700);
    expect(clockText(29_700 + 59)).toBe("08:15");
    expect(clockText(25 * 3600)).toBe("01:00");
  });
});

describe("pages", () => {
  it("picks the page from the path", () => {
    expect(["/", "/easy", "/easy/", "/pro", "/elsewhere"].map(pageOf)).toEqual([
      "landing",
      "easy",
      "easy",
      "pro",
      "landing",
    ]);
  });
});
