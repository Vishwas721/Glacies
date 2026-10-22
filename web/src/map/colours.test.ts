import { describe, expect, it } from "vitest";

import { upperBound, viridis } from "./colours";

describe("viridis", () => {
  it("runs from dark purple to yellow and clamps outside [0, 1]", () => {
    expect(viridis(0)).toEqual([68, 1, 84]);
    expect(viridis(1)).toEqual([253, 231, 37]);
    expect(viridis(-3)).toEqual(viridis(0));
    expect(viridis(7)).toEqual(viridis(1));
    expect(viridis(Number.NaN)).toEqual(viridis(0));
  });
});

describe("upperBound", () => {
  it("tops the scale at a high quantile of the positive values, not at an outlier", () => {
    const values = [0, 0, ...Array.from({ length: 99 }, (_, i) => i + 1), 10_000];

    expect(upperBound(values)).toBe(99);
    expect(upperBound([0, 0])).toBe(1);
  });
});
