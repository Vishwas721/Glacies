// How to read each comparison metric: which way is better, and what it measures. The wording
// follows the definitions in src/glacies/assignment/metrics.py and analytics/accessibility.py.

export type Reading = "better" | "worse" | "no change" | null;
type Direction = "lower" | "higher" | null;

// First match wins; `null` means the change is neither good nor bad by itself (more metro
// entries can mean better service or riders pushed off buses).
const DIRECTIONS: [RegExp, Direction][] = [
  [/Population reaching under/, "lower"],
  [/^Gini/, "lower"],
  [/reachable within|connected within/, "higher"],
  [/Mean door-to-door time/, "lower"],
  [/travel time|waiting|walking|transfers/, "lower"],
  [/crowding|above crush|above design capacity/, "lower"],
];

export function direction(metric: string): Direction {
  return DIRECTIONS.find(([pattern]) => pattern.test(metric))?.[1] ?? null;
}

/** Whether a change is an improvement; null when the metric has no better direction. */
export function reading(metric: string, delta: number): Reading {
  const d = direction(metric);
  if (d === null) return null;
  if (delta === 0) return "no change";
  return delta < 0 === (d === "lower") ? "better" : "worse";
}

export const DEFINITIONS: Record<string, string> = {
  "Assignment: travel time per transit trip":
    "Minutes in vehicles, waiting, walking and riding to a station, averaged over the AM-peak transit trips assigned to the network.",
  "Assignment: waiting per transit trip":
    "Minutes spent waiting for a vehicle, averaged over transit trips.",
  "Assignment: transfers per transit trip": "Vehicles boarded per transit trip, minus one.",
  "Estimated jobs reachable within 45 min (p50, population-weighted)":
    "Share of the city's estimated jobs (a building and job-POI proxy) each zone reaches within 45 min at the median departure, averaged over zones weighted by residents.",
  "Assignment: crowding, peak passenger-km above design capacity":
    "Share of passenger-km in the report hour travelled in vehicles loaded above design capacity (seats plus 6 standing per m²).",
  "Assignment: metro gate entries":
    "Passes through metro fare gates by the assigned trips. Neither good nor bad by itself: riders can arrive from better feeders or be pushed off buses.",
};
