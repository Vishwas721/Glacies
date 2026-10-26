import { describe, expect, it } from "vitest";

import type { RouteDetail, RouteSummary } from "../api/types";
import { emptyDraft } from "./draft";
import { draftLines, draftRouteIdx } from "./proposal";

const summary = (idx: number, route_id: string): RouteSummary => ({
  route_idx: idx,
  feed: "f",
  route_id,
  short_name: route_id,
  long_name: null,
  mode: "bus",
  patterns: 1,
  trips: 10,
  window_trips: 2,
});

const detail = (idx: number, route_id: string): RouteDetail => ({
  fields: {},
  route: summary(idx, route_id),
  features: [
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [77.5, 12.9],
          [77.6, 12.95],
        ],
      },
      properties: {
        pattern_idx: 0,
        direction_id: 0,
        headsign: null,
        stops: [0, 1],
        trips: 10,
        window_trips: 2,
      },
    },
  ],
});

describe("draft on the map", () => {
  it("draws removed routes, frequency changes and added routes", () => {
    const draft = {
      ...emptyDraft(),
      removed: ["f:A"],
      headway: { "f:B": 0.5, "f:C": 1 },
      added: [
        {
          type: "add_route" as const,
          route_id: "NEW",
          mode: "bus",
          feed: "f",
          stops: ["s1", "s2", "missing"],
          one_way: false,
          headway_secs: 600,
          span: ["07:00", "10:00"] as [string, string],
          speed_kmh: 20,
        },
      ],
    };
    const routes = [summary(0, "A"), summary(1, "B"), summary(2, "C"), summary(3, "D")];
    const stops = new Map<string, [number, number]>([
      ["f:s1", [77.55, 12.91]],
      ["f:s2", [77.58, 12.93]],
    ]);

    expect(draftRouteIdx(draft, routes)).toEqual([0, 1, 2]);
    const lines = draftLines(draft, [detail(0, "A"), detail(1, "B"), detail(2, "C")], stops);

    expect(lines.map((l) => [l.name, l.kind])).toEqual([
      ["A", "removed"],
      ["B", "modified"],
      ["NEW", "added"],
    ]);
    expect(lines[2]!.path).toEqual([
      [77.55, 12.91],
      [77.58, 12.93],
    ]);
  });

  it("finds the stops of a route added without a feed by their id", () => {
    const draft = {
      ...emptyDraft(),
      added: [
        {
          type: "add_route" as const,
          route_id: "NEW",
          mode: "bus",
          stops: ["s1", "s2"],
          one_way: true,
          headway_secs: 600,
          span: ["07:00", "10:00"] as [string, string],
          speed_kmh: 20,
        },
      ],
    };
    const stops = new Map<string, [number, number]>([
      ["f:s1", [77.55, 12.91]],
      ["g:s2", [77.58, 12.93]],
    ]);

    expect(draftLines(draft, [], stops)[0]!.path).toHaveLength(2);
  });
});
