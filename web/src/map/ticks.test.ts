import { describe, expect, it } from "vitest";

import { tickLabel, tickStep } from "./ticks";

describe("edge ticks", () => {
  it("picks a step giving at most eight ticks", () => {
    expect(tickStep(0.6)).toBe(0.1);
    expect(tickStep(0.3)).toBe(0.05);
    expect(tickStep(2.5)).toBe(0.5);
  });

  it("labels degrees with the decimals the step needs", () => {
    expect(tickLabel(77.65, 0.05, "E", "W")).toBe("77.65°E");
    expect(tickLabel(12.9, 0.1, "N", "S")).toBe("12.9°N");
    expect(tickLabel(77.5, 0.5, "E", "W")).toBe("77.5°E");
    expect(tickLabel(-0.2, 0.2, "N", "S")).toBe("0.2°S");
  });
});
