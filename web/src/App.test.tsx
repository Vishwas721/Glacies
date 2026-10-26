import type { Layer, PickingInfo } from "@deck.gl/core";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { CITY, fakeApi, renderWithClient } from "./testing";

// jsdom has no WebGL: the map is replaced by a list of the layers it would draw.
let drawn: Layer[] = [];
let click: ((info: PickingInfo) => void) | undefined;
vi.mock("./map/MapView", () => ({
  MapView: ({
    layers,
    attribution,
    onClick,
  }: {
    layers: Layer[];
    attribution: string;
    onClick?: (info: PickingInfo) => void;
  }) => {
    drawn = layers;
    click = onClick;
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
  it("lays out the panels and draws the network and accessibility", async () => {
    fakeApi(CITY);

    renderWithClient(<App />);

    expect(await screen.findByRole("heading", { name: "Toyville" })).toBeInTheDocument();
    expect(screen.getByText(/timetable of 2026-10-13/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Modes" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Explore the network" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    await waitFor(() => expect(layerIds()).toEqual(["zones-accessibility", "network"]));
    expect(screen.getByTestId("map").dataset.attribution).toContain("OpenStreetMap (ODbL-1.0)");
  });

  it("switches modes and keeps the mode in the address bar", async () => {
    fakeApi(CITY);
    renderWithClient(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Design" }));

    expect(screen.getByRole("complementary", { name: "Design a scenario" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Design" })).toHaveAttribute("aria-current", "page");
    expect(window.location.search).toBe("?mode=design");
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
    fireEvent.click(
      within(screen.getByRole("group", { name: "Zones" })).getByRole("radio", { name: "None" }),
    );

    await waitFor(() => expect(layerIds()).toEqual(["stops"]));
  });

  it("shows baseline loads without claiming they are a scenario's", async () => {
    fakeApi(CITY);
    renderWithClient(<App />);

    fireEvent.click(await screen.findByRole("radio", { name: "Peak-hour crowding" }));

    expect(screen.getByLabelText("Load legend")).not.toHaveTextContent("Loads show the scenario");
  });

  it("inspects a zone clicked on the map with every value labelled", async () => {
    fakeApi(CITY);
    renderWithClient(<App />);
    await waitFor(() => expect(layerIds()).toContain("zones-accessibility"));

    act(() =>
      click?.({
        layer: { id: "zones-accessibility" },
        object: { h3: "8861892a1bfffff", value: 0 },
      } as unknown as PickingInfo),
    );

    const card = await screen.findByRole("region", { name: "Selected zone" });
    expect(card).toHaveTextContent("8861892a1bfffff");
    expect(card).toHaveTextContent("Residents120");
    expect(within(card).getAllByText("Estimated")).toHaveLength(2);
    expect(card).toHaveTextContent("Estimated jobs within 45 min (p50)");
    fireEvent.click(within(card).getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("region", { name: "Selected zone" })).not.toBeInTheDocument();
  });

  it("says when the API is not reachable", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));

    renderWithClient(<App />);

    expect(await screen.findByText(/The API is not reachable/)).toBeInTheDocument();
  });
});
