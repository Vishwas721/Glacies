import { describe, expect, it } from "vitest";

import type { AddRoute, RouteSummary, Scenario } from "../api/types";
import { emptyDraft, fromScenario, toScenario } from "./draft";
import { validateScenario } from "./validate";

const route = (feed: string, route_id: string): RouteSummary => ({
  route_idx: 0,
  feed,
  route_id,
  short_name: route_id,
  long_name: null,
  mode: "bus",
  patterns: 1,
  trips: 10,
  window_trips: 2,
});

const feeder: AddRoute = {
  type: "add_route",
  route_id: "NEW-1",
  mode: "bus",
  feed: "bmtc_gtfs",
  stops: ["S1", "S2"],
  one_way: false,
  headway_secs: 600,
  span: ["07:00", "22:00"],
  speed_kmh: 20,
};

describe("toScenario", () => {
  it("writes removals, headway changes and new routes in a stable order", () => {
    const scenario = toScenario({
      ...emptyDraft(),
      scenarioId: "mix",
      title: "Mix",
      removed: ["bmtc_gtfs:B", "bmtc_gtfs:A"],
      headway: { "bmtc_gtfs:C": 0.5, "bmtc_gtfs:D": 1, "bmtc_gtfs:A": 0.5 },
      added: [feeder],
    });

    expect(scenario.mutations).toEqual([
      { type: "remove_route", feed: "bmtc_gtfs", route_id: "A" },
      { type: "remove_route", feed: "bmtc_gtfs", route_id: "B" },
      { type: "modify_headway", feed: "bmtc_gtfs", route_id: "C", headway_factor: 0.5 },
      feeder,
    ]);
    expect(validateScenario(scenario)).toEqual([]);
  });

  it("keys routes by feed so ids repeated across feeds stay distinct", () => {
    const scenario = toScenario({
      ...emptyDraft(),
      scenarioId: "x",
      title: "X",
      removed: ["bmrcl_gtfs:1"],
    });

    expect(scenario.mutations[0]).toEqual({
      type: "remove_route",
      feed: "bmrcl_gtfs",
      route_id: "1",
    });
  });
});

describe("fromScenario", () => {
  it("round-trips what the builder can edit and reports what it cannot", () => {
    const routes = [
      route("bmtc_gtfs", "1066"),
      route("bmtc_gtfs", "2255"),
      route("a", "9"),
      route("b", "9"),
    ];
    const saved: Scenario = {
      schema_version: 1,
      scenario_id: "orr",
      title: "ORR",
      mutations: [
        { type: "modify_headway", route_id: "1066", headway_factor: 0.5 },
        { type: "remove_route", route_id: "2255" },
        { type: "remove_route", route_id: "9" },
        { type: "modify_headway", route_id: "1066", headway_secs: 300, feed: "bmtc_gtfs" },
        feeder,
      ],
    };

    const { draft, unsupported } = fromScenario(saved, routes);

    expect(draft.headway).toEqual({ "bmtc_gtfs:1066": 0.5 });
    expect(draft.removed).toEqual(["bmtc_gtfs:2255"]);
    expect(draft.added).toEqual([feeder]);
    expect(unsupported).toHaveLength(2);
  });

  it("reads mutations as the API sends them, with absent fields as null", () => {
    const fromApi = {
      schema_version: 1,
      scenario_id: "demo",
      title: "Demo",
      mutations: [
        {
          type: "modify_headway",
          route_id: "1066",
          feed: null,
          headway_factor: 0.5,
          headway_secs: null,
          window: null,
        },
        { ...feeder, name: null, return_stops: null, dwell_secs: null },
      ],
    } as unknown as Scenario;

    const { draft, unsupported } = fromScenario(fromApi, [route("bmtc_gtfs", "1066")]);

    expect(unsupported).toEqual([]);
    expect(draft.headway).toEqual({ "bmtc_gtfs:1066": 0.5 });
    expect(draft.added).toEqual([feeder]);
    expect(validateScenario(toScenario(draft))).toEqual([]);
  });
});

describe("validateScenario", () => {
  it("names the field that is wrong, not every other mutation kind", () => {
    const bad = toScenario({
      ...emptyDraft(),
      scenarioId: "Bad Id",
      title: "",
      added: [{ ...feeder, speed_kmh: 0 }],
    });

    const problems = validateScenario(bad);

    expect(problems).toContain('/scenario_id must match pattern "^[a-z0-9][a-z0-9_-]*$"');
    expect(problems.some((p) => p.startsWith("/title"))).toBe(true);
    expect(problems.some((p) => p.startsWith("/mutations/0/speed_kmh"))).toBe(true);
    expect(problems.some((p) => p.includes("remove_route") || p.includes("required"))).toBe(false);
  });

  it("requires at least one change", () => {
    const empty = toScenario({ ...emptyDraft(), scenarioId: "x", title: "X" });

    expect(validateScenario(empty)).toEqual(["/mutations must NOT have fewer than 1 items"]);
  });
});
