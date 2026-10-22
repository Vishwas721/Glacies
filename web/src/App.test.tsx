import type { Layer } from "@deck.gl/core";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { CITY, fakeApi, renderWithClient } from "./testing";

// jsdom has no WebGL: the map is replaced by a list of the layers it would draw.
let drawn: Layer[] = [];
vi.mock("./map/MapView", () => ({
  MapView: ({ layers, attribution }: { layers: Layer[]; attribution: string }) => {
    drawn = layers;
    return (
      <div data-testid="map" data-attribution={attribution}>
        {layers.map((l) => l.id).join(" ")}
      </div>
    );
  },
}));

beforeEach(() => {
  drawn = [];
});
afterEach(() => vi.unstubAllGlobals());

const layerIds = () => drawn.map((l) => l.id);

describe("App", () => {
  it("lays out the three panels and draws the network and accessibility", async () => {
    fakeApi(CITY);

    renderWithClient(<App />);

    expect(await screen.findByText(/Toyville · timetable of 2026-10-13/)).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Scenario" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    await waitFor(() => expect(layerIds()).toEqual(["zones-accessibility", "network"]));
    expect(screen.getByTestId("map").dataset.attribution).toContain("OpenStreetMap (ODbL-1.0)");
  });

  it("labels the legend with the layer's data nature", async () => {
    fakeApi(CITY);
    renderWithClient(<App />);

    const legend = await screen.findByLabelText("Legend");

    expect(within(legend).getAllByText("Simulated")).toHaveLength(2);
    fireEvent.click(screen.getByRole("radio", { name: "Population" }));
    await waitFor(() => expect(within(legend).getAllByText("Estimated")).toHaveLength(2));
    expect(layerIds()).toContain("zones-population");
  });

  it("turns layers on and off", async () => {
    fakeApi(CITY);
    renderWithClient(<App />);
    await waitFor(() => expect(layerIds()).toContain("network"));

    fireEvent.click(screen.getByRole("checkbox", { name: "Bus and metro network" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Stops" }));
    fireEvent.click(screen.getByRole("radio", { name: "None" }));

    await waitFor(() => expect(layerIds()).toEqual(["stops"]));
  });

  it("says when the API is not reachable", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));

    renderWithClient(<App />);

    expect(await screen.findByText(/The API is not reachable/)).toBeInTheDocument();
  });
});
