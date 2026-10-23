// Test fixtures: a finished simulation "k1" of a scenario that runs route 10 twice as often.

const label = (nature: string, unit: string | null, description = "") => ({
  nature,
  unit,
  description,
});

const H3 = ["8861892a1bfffff", "8861892a1dfffff"];

export const RESULT = {
  "GET /api/cities/toyville/results": [
    {
      key: "k1",
      scenario_id: "faster_10",
      title: "Route 10 twice as often",
      finished_at: "2026-10-22T10:15:00+00:00",
      assignment: true,
      compared: true,
    },
    {
      key: "k0",
      scenario_id: "older_run",
      title: "Before comparisons were stored",
      finished_at: "2026-10-08T10:00:00+00:00",
      assignment: false,
      compared: false,
    },
  ],
  "GET /api/simulations": [
    {
      id: "sim_1",
      city: "toyville",
      scenario_id: "faster_10",
      status: "completed",
      progress: {
        stage: "comparison",
        stage_index: 4,
        stages: [],
        message: null,
        done: null,
        total: null,
      },
      result_key: "k1",
      cached: false,
      error: null,
      created_at: "2026-10-22T10:00:00+00:00",
      started_at: "2026-10-22T10:00:01+00:00",
      finished_at: "2026-10-22T10:15:00+00:00",
    },
  ],
  "GET /api/cities/toyville/results/k1/metrics": {
    rows: [
      {
        metric: "Assignment: travel time per transit trip",
        unit: "minutes",
        nature: "simulated",
        baseline: 77.4,
        scenario: 77.3926,
        delta: -0.0074,
      },
      {
        metric: "Estimated jobs reachable within 45 min (p50, population-weighted)",
        unit: "share",
        nature: "simulated",
        baseline: 0.0274,
        scenario: 0.027417,
        delta: 0.000017,
      },
      {
        metric: "Trips in the service-day timetable",
        unit: "count",
        nature: "simulated",
        baseline: 3,
        scenario: 5,
        delta: 2,
      },
    ],
  },
  "GET /api/cities/toyville/results/k1/changes": {
    fields: {
      trips_removed: label("assumed", "trips"),
      trips_added: label("assumed", "trips"),
      boardings_baseline: label("simulated", "pax"),
      boardings_scenario: label("simulated", "pax"),
      boardings_delta: label("simulated", "pax"),
    },
    routes: [
      {
        mutation_idx: 0,
        kind: "modified",
        route_id: "R1",
        route_idx: [0],
        name: "10",
        mode: "bus",
        trips_removed: 0,
        trips_added: 2,
        boardings_baseline: 40,
        boardings_scenario: 65,
        coordinates: [
          [
            [77.02, 12.02],
            [77.03, 12.03],
            [77.04, 12.04],
          ],
        ],
      },
    ],
    largest_boardings_changes: [
      {
        route_idx: 0,
        name: "10",
        mode: "bus",
        boardings_baseline: 40,
        boardings_scenario: 65,
        boardings_delta: 25,
      },
    ],
  },
  "GET /api/cities/toyville/results/k1/accessibility": {
    fields: {
      est_jobs_share: label("simulated", "share", "Share of estimated jobs reachable."),
      est_jobs_share_delta: label("simulated", "share", "Scenario minus baseline."),
    },
    percentile: 50,
    threshold_min: 45,
    zone_idx: [0, 1],
    h3_cell: H3,
    edge_zone: [false, false],
    est_jobs_share: [0.021, 0.04],
    population_share: [0.1, 0.2],
    est_jobs_share_delta: [0.001, 0],
  },
  "GET /api/cities/toyville/results/k1/checks": {
    fields: {
      stations: label("observed", "count"),
      level_ratio: label("simulated", "ratio"),
      segment_share: label("simulated", "share"),
      passenger_share: label("simulated", "share"),
    },
    report_window: ["08:30", "09:30"],
    station_fits: [
      { set: "excluded", stations: 15, level_ratio: 4.95 },
      { set: "held_out", stations: 15, level_ratio: 0.98 },
      { set: "training", stations: 53, level_ratio: 1.26 },
    ],
    bus_load_bands: [
      { band: "under 0.5", segment_share: 0.55, passenger_share: 0.15 },
      { band: "0.5-1.0", segment_share: 0.19, passenger_share: 0.19 },
      { band: "1.0-1.5", segment_share: 0.1, passenger_share: 0.14 },
      { band: "over 1.5", segment_share: 0.16, passenger_share: 0.52 },
    ],
  },
  "GET /api/cities/toyville/results/k1/flows": {
    fields: {
      passengers: label("simulated", "pax"),
      load_factor: label("simulated", "ratio"),
      passenger_segments: label("simulated", "pax"),
    },
    frame_minutes: 15,
    demand_window: ["08:00", "10:00"],
    report_window: ["08:30", "09:30"],
    frames: [
      { start: "08:00", partial: true, passenger_segments: 12 },
      { start: "08:15", partial: true, passenger_segments: 30 },
      { start: "08:30", partial: false, passenger_segments: 55 },
    ],
    pairs: {
      from_stop_idx: [3],
      to_stop_idx: [4],
      coordinates: [[77.02, 12.02, 77.03, 12.03]],
      mode: ["bus"],
    },
    frame_idx: [0, 1, 2],
    pair_idx: [0, 0, 0],
    passengers: [12, 30, 55],
    load_factor: [0.2, 0.5, 0.92],
    dropped_passengers: 0,
  },
};
