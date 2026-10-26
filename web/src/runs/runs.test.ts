import { describe, expect, it } from "vitest";

import { duration } from "./runs";

describe("duration", () => {
  it("reads the time between two recorded timestamps", () => {
    expect(duration("2026-10-23T10:00:00+00:00", "2026-10-23T10:00:42+00:00")).toBe("42 s");
    expect(duration("2026-10-23T10:00:00+00:00", "2026-10-23T10:05:00+00:00")).toBe("5 min 0 s");
    expect(duration("2026-10-23T10:00:00+00:00", "2026-10-23T11:12:00+00:00")).toBe("1 h 12 min");
  });
});
