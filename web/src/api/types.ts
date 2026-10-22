// Shapes of the Glacies API responses (src/glacies/api/routers/*). Hand-written to match the
// Pydantic models; the OpenAPI document at /docs is the reference.

export type Nature = "observed" | "estimated" | "simulated" | "assumed";

export interface FieldInfo {
  nature: Nature;
  unit: string | null;
  description: string;
}

export interface Labelled {
  fields: Record<string, FieldInfo>;
}

export interface Source {
  id: string;
  kind: string;
  source: string;
  url: string;
  license: string;
  nature: Nature;
  verified: boolean;
}

export interface CityDetail {
  id: string;
  name: string;
  country: string;
  timezone: string;
  bbox: [number, number, number, number];
  service_date: string | null;
  window: [string, string];
  accessibility: {
    percentiles: number[];
    thresholds_min: number[];
    headline_percentile: number;
    headline_threshold_min: number;
  };
  outputs: { name: string; available: boolean; command: string }[];
  sources: Source[];
}

export interface RouteSummary {
  route_idx: number;
  feed: string;
  route_id: string;
  short_name: string | null;
  long_name: string | null;
  mode: string;
  patterns: number;
  trips: number;
  window_trips: number;
}

export interface RouteList extends Labelled {
  window: { start: string; end: string };
  routes: RouteSummary[];
}

export type LonLat = [number, number];

export interface PatternFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: LonLat[] };
  properties: {
    pattern_idx: number;
    direction_id: number | null;
    headsign: string | null;
    stops: number[];
    trips: number;
    window_trips: number;
  };
}

export interface RouteDetail extends Labelled {
  route: RouteSummary;
  features: PatternFeature[];
}

export interface StopFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: LonLat };
  properties: {
    stop_idx: number;
    feed: string;
    stop_id: string;
    name: string | null;
    station: boolean;
    parent_stop_idx: number | null;
    modes: string[];
    routes: number;
  };
}

export interface StopCollection extends Labelled {
  features: StopFeature[];
}

export interface SegmentFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [LonLat, LonLat] };
  properties: {
    from_stop_idx: number;
    to_stop_idx: number;
    modes: string[];
    routes: number;
    trips: number;
    window_trips: number;
  };
}

export interface Network extends Labelled {
  window: { start: string; end: string };
  features: SegmentFeature[];
}

export interface Zones extends Labelled {
  resolution: number;
  zone_idx: number[];
  h3_cell: string[];
  population: number[];
  est_employment_share: number[] | null;
}

export interface Accessibility extends Labelled {
  percentile: number;
  threshold_min: number;
  zone_idx: number[];
  h3_cell: string[];
  edge_zone: boolean[];
  est_jobs_share: number[];
  population_share: number[];
  est_jobs_share_delta: number[] | null;
}

// Scenario documents (schemas/scenario.schema.json).
export interface RemoveRoute {
  type: "remove_route";
  route_id: string;
  feed?: string;
}

export interface ModifyHeadway {
  type: "modify_headway";
  route_id: string;
  feed?: string;
  headway_factor?: number;
  headway_secs?: number;
  window?: [string, string];
}

export interface AddRoute {
  type: "add_route";
  route_id: string;
  name?: string;
  mode: string;
  feed?: string;
  stops: string[];
  return_stops?: string[];
  one_way: boolean;
  headway_secs: number;
  span: [string, string];
  speed_kmh: number;
  dwell_secs?: number;
}

export type Mutation = RemoveRoute | ModifyHeadway | AddRoute;

export interface Scenario {
  schema_version: 1;
  scenario_id: string;
  base_network?: "baseline";
  title: string;
  description?: string;
  expected_change?: string;
  mutations: Mutation[];
}

export interface ScenarioSummary {
  scenario_id: string;
  title: string;
  source: "repository" | "user";
  editable: boolean;
  mutation_types: string[];
}

export interface ScenarioRecord {
  source: "repository" | "user";
  editable: boolean;
  scenario: Scenario;
}

export type SimulationStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Simulation {
  id: string;
  city: string;
  scenario_id: string;
  status: SimulationStatus;
  progress: {
    stage: string | null;
    stage_index: number | null;
    stages: string[];
    message: string | null;
    done: number | null;
    total: number | null;
  };
  result_key: string | null;
  cached: boolean | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
