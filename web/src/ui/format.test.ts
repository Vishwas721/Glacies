import { describe, expect, it } from "vitest";

import { format, formatDelta, formatPair } from "./format";

describe("format", () => {
  it("shows shares as percentages and minutes as min", () => {
    expect(format(0.027416, "share")).toBe("2.74 %");
    expect(format(77.4, "minutes")).toBe("77.4 min");
    expect(format(1.36, "index")).toBe("1.36");
    expect(format(219565.4, "count")).toBe("2,19,565");
  });
});

describe("formatDelta", () => {
  it("keeps small changes visible with two significant digits", () => {
    expect(formatDelta(-0.0074, "minutes")).toBe("−0.0074 min");
    expect(formatDelta(0.000017, "share")).toBe("+0.0017 pp");
    expect(formatDelta(19, "count")).toBe("+19");
    expect(formatDelta(3040.2, "pax")).toBe("+3,040 pax");
    expect(formatDelta(0, "minutes")).toBe("no change");
  });
});

describe("formatPair", () => {
  it("adds decimals until baseline and scenario differ", () => {
    expect(formatPair(77.398, 77.392, "minutes")).toEqual(["77.40 min", "77.39 min"]);
    expect(formatPair(0.027399, 0.027409, "share")).toEqual(["2.740 %", "2.741 %"]);
    expect(formatPair(219565, 219506, "count")).toEqual(["2,19,565", "2,19,506"]);
  });

  it("leaves equal values and already distinct values alone", () => {
    expect(formatPair(13.7, 13.7, "minutes")).toEqual(["13.7 min", "13.7 min"]);
    expect(formatPair(12.5, 14.25, "minutes")).toEqual(["12.5 min", "14.3 min"]);
    expect(formatPair(0.0494, 0.05, "share")).toEqual(["4.94 %", "5.00 %"]);
  });
});
