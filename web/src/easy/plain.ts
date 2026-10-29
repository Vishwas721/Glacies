// The Easy view's answer in plain words: a few of the comparison's metrics, renamed for someone
// who has never seen a transport model, with which way is better (compare/ledger.ts).

import type { ChangedRoute, MetricRow } from "../api/types";
import { reading, type Reading } from "../compare/ledger";

export interface PlainMetric {
  label: string;
  hint: string;
  row: MetricRow;
  reading: Reading;
}

// The comparison's metric names, in the order the answer reads them.
const PLAIN: [string, string, string][] = [
  [
    "Assignment: waiting per transit trip",
    "Waiting for a bus or train",
    "Average minutes spent waiting, per trip.",
  ],
  [
    "Assignment: travel time per transit trip",
    "The whole journey",
    "Average door-to-door minutes, per trip by bus or metro.",
  ],
  [
    "Estimated jobs reachable within 45 min (p50, population-weighted)",
    "Jobs within 45 minutes",
    "Share of the city's estimated jobs the average resident can reach within 45 minutes.",
  ],
  [
    "Assignment: crowding, peak passenger-km above design capacity",
    "Travel in overcrowded vehicles",
    "Share of the busiest hour's travel in buses and trains fuller than they are designed for.",
  ],
  [
    "Assignment: metro gate entries",
    "Metro entries",
    "People entering metro stations. Neither good nor bad by itself.",
  ],
];

const GAINING = "Zones gaining access at the headline (45 min, p50)";
const LOSING = "Zones losing access at the headline (45 min, p50)";

export function plainMetrics(rows: MetricRow[]): PlainMetric[] {
  return PLAIN.flatMap(([metric, label, hint]) => {
    const row = rows.find((r) => r.metric === metric);
    return row ? [{ label, hint, row, reading: reading(metric, row.delta) }] : [];
  });
}

/** Areas that can reach more and fewer estimated jobs within 45 minutes. */
export function areasMoved(rows: MetricRow[]): { gaining: MetricRow; losing: MetricRow } | null {
  const gaining = rows.find((r) => r.metric === GAINING);
  const losing = rows.find((r) => r.metric === LOSING);
  return gaining && losing ? { gaining, losing } : null;
}

/** The size of a change against its starting value, e.g. "0.08 % less"; null if it cannot be said. */
export function relative(row: MetricRow): string | null {
  if (row.delta === 0) return "no change";
  if (row.baseline === 0 || row.unit === "share") return null;
  const pct = Math.abs(row.delta / row.baseline) * 100;
  const digits = pct >= 10 ? 0 : pct >= 1 ? 1 : Math.min(3, 1 - Math.floor(Math.log10(pct)));
  return `${pct.toLocaleString("en-IN", { maximumFractionDigits: digits })} % ${row.delta < 0 ? "less" : "more"}`;
}

/** What a scenario did to one route, in words. */
export function routeChange(route: ChangedRoute): string {
  if (route.kind === "removed") return "taken away";
  if (route.kind === "added") return "new route";
  if (route.trips_added > route.trips_removed) return "runs more often";
  if (route.trips_added < route.trips_removed) return "runs less often";
  return "timetable changed";
}

export const READING_WORD: Record<NonNullable<Reading>, string> = {
  better: "better",
  worse: "worse",
  "no change": "no change",
};
