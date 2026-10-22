// Test helpers: a fake API answering by path, and rendering inside a fresh QueryClient.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

export interface Call {
  method: string;
  path: string;
  body: unknown;
}

type Handler = (call: Call) => unknown;

/** Replace fetch: `routes` maps "METHOD /path" (query string ignored) to a response body. */
export function fakeApi(routes: Record<string, unknown | Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (input: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = input.split("?")[0]!;
    const call = { method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const entry = routes[`${method} ${path}`];
    if (entry === undefined) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
      );
    }
    const body = typeof entry === "function" ? (entry as Handler)(call) : entry;
    const status = method === "POST" ? 201 : 200;
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  });
  return calls;
}

export function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const label = (nature: string, unit: string | null, description = "") => ({
  nature,
  unit,
  description,
});

// A two-route city answering every endpoint the screen loads.
export const CITY = {
  "GET /api/cities": [{ id: "toyville", name: "Toyville", country: "XX" }],
  "GET /api/cities/toyville": {
    id: "toyville",
    name: "Toyville",
    country: "XX",
    timezone: "UTC",
    bbox: [77.0, 12.0, 77.1, 12.1],
    service_date: "2026-10-13",
    window: ["07:30", "09:30"],
    accessibility: {
      percentiles: [25, 50, 75],
      thresholds_min: [15, 30, 45, 60],
      headline_percentile: 50,
      headline_threshold_min: 45,
    },
    outputs: [],
    sources: [
      {
        id: "osm",
        kind: "osm_pbf",
        source: "OpenStreetMap",
        url: "https://openstreetmap.org",
        license: "ODbL-1.0",
        nature: "observed",
        verified: true,
      },
    ],
  },
  "GET /api/cities/toyville/routes": {
    fields: {
      patterns: label("observed", "count"),
      trips: label("observed", "trips"),
      window_trips: label("observed", "trips"),
    },
    window: { start: "07:30", end: "09:30" },
    routes: [
      {
        route_idx: 0,
        feed: "toy_gtfs",
        route_id: "R1",
        short_name: "10",
        long_name: "A to C",
        mode: "bus",
        patterns: 1,
        trips: 2,
        window_trips: 2,
      },
      {
        route_idx: 1,
        feed: "toy_gtfs",
        route_id: "R3",
        short_name: "M1",
        long_name: "Central to D",
        mode: "metro",
        patterns: 1,
        trips: 1,
        window_trips: 0,
      },
    ],
  },
  "GET /api/cities/toyville/network": {
    fields: {
      routes: label("observed", "routes"),
      trips: label("observed", "trips"),
      window_trips: label("observed", "trips"),
    },
    window: { start: "07:30", end: "09:30" },
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [77.02, 12.02],
            [77.03, 12.03],
          ],
        },
        properties: {
          from_stop_idx: 3,
          to_stop_idx: 4,
          modes: ["bus"],
          routes: 1,
          trips: 2,
          window_trips: 2,
        },
      },
    ],
  },
  "GET /api/cities/toyville/stops": {
    fields: { routes: label("observed", "routes") },
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [77.02, 12.02] },
        properties: {
          stop_idx: 3,
          feed: "toy_gtfs",
          stop_id: "A",
          name: "Stop A",
          station: false,
          parent_stop_idx: null,
          modes: ["bus"],
          routes: 1,
        },
      },
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [77.04, 12.04] },
        properties: {
          stop_idx: 5,
          feed: "toy_gtfs",
          stop_id: "C",
          name: "Stop C",
          station: false,
          parent_stop_idx: null,
          modes: ["bus"],
          routes: 1,
        },
      },
    ],
  },
  "GET /api/cities/toyville/zones": {
    fields: {
      population: label("estimated", "people", "Residents per zone."),
      est_employment_share: label("estimated", "share", "Share of estimated employment."),
    },
    resolution: 8,
    zone_idx: [0, 1],
    h3_cell: ["8861892a1bfffff", "8861892a1dfffff"],
    population: [120, 80],
    est_employment_share: [0.75, 0.25],
  },
  "GET /api/cities/toyville/results/baseline/accessibility": {
    fields: { est_jobs_share: label("simulated", "share", "Share of estimated jobs reachable.") },
    percentile: 50,
    threshold_min: 45,
    zone_idx: [0, 1],
    h3_cell: ["8861892a1bfffff", "8861892a1dfffff"],
    edge_zone: [false, false],
    est_jobs_share: [0.02, 0.04],
    population_share: [0.1, 0.2],
    est_jobs_share_delta: null,
  },
  "GET /api/cities/toyville/scenarios": [],
};
