import type { PickingInfo } from "@deck.gl/core";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { type Call, CITY, fakeApi, renderWithClient } from "../testing";

let click: ((info: PickingInfo) => void) | undefined;
vi.mock("../map/MapView", () => ({
  MapView: ({ onClick }: { onClick?: (info: PickingInfo) => void }) => {
    click = onClick;
    return <div data-testid="map" />;
  },
}));
afterEach(() => vi.unstubAllGlobals());

const stop = (id: string) =>
  CITY["GET /api/cities/toyville/stops"].features.find((f) => f.properties.stop_id === id)!;

const RUNNING = {
  id: "sim_1",
  city: "toyville",
  scenario_id: "no_r1",
  status: "running",
  progress: {
    stage: "travel-time matrix",
    stage_index: 1,
    stages: [
      "applying mutations",
      "travel-time matrix",
      "accessibility",
      "assignment with crowding",
      "comparison",
    ],
    message: "travel-time matrix: 3 of 10 origins",
    done: 2,
    total: 4,
  },
  result_key: null,
  cached: null,
  error: null,
  created_at: "2026-10-22T10:00:00+00:00",
  started_at: "2026-10-22T10:00:01+00:00",
  finished_at: null,
};

async function ready() {
  renderWithClient(<App />);
  await screen.findByRole("searchbox", { name: "Find a route" });
}

function fill(id: string, title: string) {
  const scenario = screen.getByRole("region", { name: "Scenario" });
  fireEvent.change(within(scenario).getByPlaceholderText("my_scenario"), { target: { value: id } });
  fireEvent.change(within(scenario).getByLabelText("Title"), { target: { value: title } });
}

const posted = (calls: Call[], path: string) =>
  calls.filter((c) => c.method === "POST" && c.path === path);

describe("Scenario builder", () => {
  it("removes a route, saves, simulates and shows progress", async () => {
    const calls = fakeApi({
      ...CITY,
      "POST /api/cities/toyville/scenarios": (c: Call) => ({
        source: "user",
        editable: true,
        scenario: c.body,
      }),
      "POST /api/simulations": { job_id: "sim_1", status: "queued" },
      "GET /api/simulations/sim_1": RUNNING,
      "POST /api/simulations/sim_1/cancel": { ...RUNNING, status: "cancelled" },
    });
    await ready();

    fireEvent.change(screen.getByRole("searchbox", { name: "Find a route" }), {
      target: { value: "10" },
    });
    fireEvent.click(await screen.findByRole("checkbox", { name: "10 in service" }));
    fill("no_r1", "Without route 10");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText(/saved as no_r1/);
    expect(posted(calls, "/api/cities/toyville/scenarios")[0]!.body).toEqual({
      schema_version: 1,
      scenario_id: "no_r1",
      title: "Without route 10",
      mutations: [{ type: "remove_route", feed: "toy_gtfs", route_id: "R1" }],
    });

    fireEvent.click(screen.getByRole("button", { name: "Simulate" }));
    const status = await screen.findByRole("status");
    expect(posted(calls, "/api/simulations")[0]!.body).toEqual({
      city: "toyville",
      scenario_id: "no_r1",
    });
    await within(status).findByText("Stage 2 of 5: travel-time matrix: 3 of 10 origins");
    expect(within(status).getByRole("progressbar")).toHaveAttribute("value", "2");

    fireEvent.click(within(status).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(posted(calls, "/api/simulations/sim_1/cancel")).toHaveLength(1));
  });

  it("checks the schema before saving and shows what is wrong", async () => {
    const calls = fakeApi(CITY);
    await ready();

    fill("Bad Id", "");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const problems = await screen.findByRole("list", { name: "Problems" });
    expect(problems).toHaveTextContent("/scenario_id must match pattern");
    expect(problems).toHaveTextContent("/mutations must NOT have fewer than 1 items");
    expect(posted(calls, "/api/cities/toyville/scenarios")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Simulate" })).toBeDisabled();
  });

  it("shows the server's reason when it refuses a scenario", async () => {
    fakeApi({ ...CITY });
    vi.stubGlobal(
      "fetch",
      ((original) => (input: string, init?: RequestInit) =>
        init?.method === "POST"
          ? Promise.resolve(
              new Response(
                JSON.stringify({ detail: "route 'R1' has no trips on the service day" }),
                {
                  status: 422,
                },
              ),
            )
          : original(input, init))(globalThis.fetch),
    );
    await ready();

    fireEvent.change(screen.getByRole("searchbox", { name: "Find a route" }), {
      target: { value: "10" },
    });
    fireEvent.click(await screen.findByRole("checkbox", { name: "10 in service" }));
    fill("no_r1", "Without route 10");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("list", { name: "Problems" })).toHaveTextContent(
      "no trips on the service day",
    );
  });

  it("adds a route from stops picked on the map", async () => {
    const calls = fakeApi({
      ...CITY,
      "POST /api/cities/toyville/scenarios": (c: Call) => ({
        source: "user",
        editable: true,
        scenario: c.body,
      }),
    });
    await ready();

    fireEvent.click(screen.getByRole("button", { name: "Pick stops on the map" }));
    act(() => click?.({ layer: { id: "stops" }, object: stop("A") } as unknown as PickingInfo));
    act(() => click?.({ layer: { id: "stops" }, object: stop("C") } as unknown as PickingInfo));
    fireEvent.change(screen.getByLabelText(/Every/), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Add route" }));
    fill("a_to_c", "Direct A to C");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText(/saved as a_to_c/);
    const [mutation] = (
      posted(calls, "/api/cities/toyville/scenarios")[0]!.body as { mutations: unknown[] }
    ).mutations;
    expect(mutation).toEqual({
      type: "add_route",
      route_id: "NEW-1",
      mode: "bus",
      feed: "toy_gtfs",
      stops: ["A", "C"],
      one_way: false,
      headway_secs: 900,
      span: ["06:00", "22:00"],
      speed_kmh: 20,
    });
  });

  it("opens a repository scenario as an editable copy", async () => {
    fakeApi({
      ...CITY,
      "GET /api/cities/toyville/scenarios": [
        {
          scenario_id: "faster",
          title: "Faster 10",
          source: "repository",
          editable: false,
          mutation_types: ["modify_headway"],
        },
      ],
      "GET /api/cities/toyville/scenarios/faster": {
        source: "repository",
        editable: false,
        scenario: {
          schema_version: 1,
          scenario_id: "faster",
          title: "Faster 10",
          mutations: [{ type: "modify_headway", route_id: "R1", headway_factor: 0.5 }],
        },
      },
    });
    await ready();

    const open = screen.getByRole("combobox", { name: "Open scenario" });
    await within(open).findByRole("option", { name: /Faster 10/ });
    fireEvent.change(open, { target: { value: "faster" } });

    expect(await screen.findByText(/faster is a repository scenario/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("my_scenario")).toHaveValue("faster_copy");
    expect(screen.getByRole("combobox", { name: "10 frequency" })).toHaveValue("0.5");
  });
});
