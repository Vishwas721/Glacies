import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App shell", () => {
  it("renders the three-panel layout", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Glacies" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Scenario" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Metrics" })).toBeInTheDocument();
  });
});
