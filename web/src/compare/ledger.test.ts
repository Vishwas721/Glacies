import { describe, expect, it } from "vitest";

import { reading } from "./ledger";

describe("reading", () => {
  it("calls shorter journeys and waits better, longer ones worse", () => {
    expect(reading("Assignment: travel time per transit trip", -0.006)).toBe("better");
    expect(reading("Assignment: waiting per transit trip", 0.002)).toBe("worse");
    expect(reading("Assignment: transfers per transit trip", 0)).toBe("no change");
  });

  it("calls more access better and more crowding or inequality worse", () => {
    expect(reading("Estimated jobs reachable within 45 min (p50, population-weighted)", 1e-5)).toBe(
      "better",
    );
    expect(reading("Population reaching under 1 % of estimated jobs within 45 min", 0.01)).toBe(
      "worse",
    );
    expect(reading("Gini of estimated-job access within 45 min (0 equal, 1 unequal)", -0.1)).toBe(
      "better",
    );
    expect(reading("Assignment: crowding, peak passenger-km above design capacity", 0.1)).toBe(
      "worse",
    );
  });

  it("does not judge counts that cut both ways", () => {
    expect(reading("Assignment: metro gate entries", -60)).toBeNull();
    expect(reading("Trips in the service-day timetable", 265)).toBeNull();
    expect(reading("Zones gaining access at the headline (45 min, p50)", 22)).toBeNull();
  });
});
