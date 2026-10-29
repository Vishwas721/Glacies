import { describe, expect, it } from "vitest";

import type { ChangedRoute, MetricRow, StopFeature } from "../api/types";
import {
  band,
  boundsOf,
  metres,
  namedStops,
  nearestStop,
  searchStops,
  within,
  zoneAt,
  zoneCentre,
} from "./place";
import { areasMoved, plainMetrics, relative, routeChange } from "./plain";

const stop = (
  name: string | null,
  at: [number, number],
  opts: { station?: boolean; metro?: boolean } = {},
): StopFeature => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: at },
  properties: {
    stop_idx: 0,
    feed: "f",
    stop_id: String(name),
    name,
    station: opts.station ?? false,
    parent_stop_idx: null,
    modes: [opts.metro ? "metro" : "bus"],
    routes: 1,
  },
});

describe("places", () => {
  const stops = namedStops([
    stop("Market", [77.6, 12.9]),
    stop("market", [77.601, 12.9]), // the other side of the road
    stop("Market Metro", [77.61, 12.91], { metro: true }),
    stop("Market Metro", [77.611, 12.911], { station: true, metro: true }),
    stop("Supermarket Road", [77.7, 13.0]),
    stop(null, [77.0, 13.0]),
  ]);

  it("keeps one entry per name, the station's for a metro stop", () => {
    expect(stops.map((s) => [s.name, s.metro])).toEqual([
      ["Market", false],
      ["Market Metro", true],
      ["Supermarket Road", false],
    ]);
    expect(stops.find((s) => s.name === "Market Metro")!.position).toEqual([77.611, 12.911]);
  });

  it("finds names that start with the text first, metro first among those", () => {
    expect(searchStops(stops, "mark").map((s) => s.name)).toEqual([
      "Market Metro",
      "Market",
      "Supermarket Road",
    ]);
    expect(searchStops(stops, "m")).toEqual([]); // too short to search
  });

  it("measures distances and finds the nearest stop", () => {
    // One thousandth of a degree of latitude is about 111 m.
    expect(metres([77.6, 12.9], [77.6, 12.901])).toBeCloseTo(111.2, 0);
    expect(nearestStop(stops, [77.6005, 12.9])!.stop.name).toBe("Market");
    expect(nearestStop([], [0, 0])).toBeNull();
  });

  it("puts a point in its zone and back near its centre", () => {
    const zone = zoneAt([77.6, 12.9], 8);
    const [lng, lat] = zoneCentre(zone);
    expect(metres([lng, lat], [77.6, 12.9])).toBeLessThan(600); // within one res-8 cell
  });

  it("bands travel times and keeps the zones within a limit", () => {
    expect([0, 15, 15.1, 30, 45, 45.1].map(band)).toEqual([0, 0, 1, 1, 2, null]);
    expect(within(["a", "b", "c"], [10, 45, 46], 45)).toEqual(new Set(["a", "b"]));
    expect(boundsOf([], [[1, 2]])).toEqual([1, 2, 1, 2]);
    expect(boundsOf([])).toBeNull();
  });
});

const row = (metric: string, baseline: number, scenario: number, unit = "minutes"): MetricRow => ({
  metric,
  unit,
  nature: "simulated",
  baseline,
  scenario,
  delta: scenario - baseline,
});

describe("the plain answer", () => {
  const rows = [
    row("Assignment: metro gate entries", 1000, 990, "count"),
    row("Assignment: waiting per transit trip", 13.7, 13.69),
    row("Zones gaining access at the headline (45 min, p50)", 0, 44, "count"),
    row("Zones losing access at the headline (45 min, p50)", 0, 13, "count"),
  ];

  it("renames the metrics it knows, in reading order, and judges them", () => {
    const plain = plainMetrics(rows);
    expect(plain.map((m) => [m.label, m.reading])).toEqual([
      ["Waiting for a bus or train", "better"],
      ["Metro entries", null], // neither better nor worse by itself
    ]);
    expect(areasMoved(rows)).toMatchObject({ gaining: { scenario: 44 }, losing: { scenario: 13 } });
    expect(areasMoved(rows.slice(0, 2))).toBeNull();
  });

  it("says how big a change is against where it started", () => {
    expect(relative(rows[1]!)).toBe("0.073 % less");
    expect(relative(row("x", 10, 12))).toBe("20 % more");
    expect(relative(row("x", 5, 5))).toBe("no change");
    expect(relative(row("x", 0, 5))).toBeNull();
    expect(relative(row("x", 0.2, 0.3, "share"))).toBeNull(); // a share's change is in points
  });

  it("describes what a scenario did to a route", () => {
    const route = (kind: ChangedRoute["kind"], removed: number, added: number) =>
      ({ kind, trips_removed: removed, trips_added: added }) as ChangedRoute;
    expect(routeChange(route("removed", 5, 0))).toBe("taken away");
    expect(routeChange(route("added", 0, 9))).toBe("new route");
    expect(routeChange(route("modified", 0, 396))).toBe("runs more often");
    expect(routeChange(route("modified", 20, 10))).toBe("runs less often");
  });
});
