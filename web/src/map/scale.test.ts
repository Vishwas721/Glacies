import { describe, expect, it } from "vitest";

import { scaleBar } from "./scale";

describe("scaleBar", () => {
  it("shows the longest round distance that fits", () => {
    // At the equator, zoom 0 is 78,272 m per pixel; zoom 10 is about 76.4 m.
    expect(scaleBar(10, 0)).toEqual({ px: 65, label: "5 km" });
    expect(scaleBar(14, 0, 100)).toEqual({ px: 42, label: "200 m" });
  });

  it("uses a shorter distance away from the equator, where a pixel covers less ground", () => {
    expect(scaleBar(10, 60)).toEqual({ px: 52, label: "2 km" });
  });
});
