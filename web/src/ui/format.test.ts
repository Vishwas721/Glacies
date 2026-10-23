import { describe, expect, it } from "vitest";

import { format, formatDelta } from "./format";

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
