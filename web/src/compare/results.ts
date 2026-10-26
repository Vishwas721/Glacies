// Finished scenario results (listed from disk by the API) as choices to compare with.

import type { ResultSummary } from "../api/types";

export interface ResultChoice {
  key: string;
  label: string;
  finishedAt?: string;
  /** The newest run of its scenario; earlier runs were computed by older code or data. */
  latest?: boolean;
}

const when = (iso: string) => `${iso.slice(0, 16).replace("T", " ")} UTC`;

/**
 * Results with a comparison against the baseline, newest first; older cache entries without one
 * are left out. A scenario run again after a code change has several results with one title.
 */
export function comparableResults(results: ResultSummary[]): ResultChoice[] {
  const seen = new Set<string>();
  return results
    .filter((r) => r.compared)
    .sort((a, b) => b.finished_at.localeCompare(a.finished_at) || a.key.localeCompare(b.key))
    .map((r) => {
      const latest = !seen.has(r.scenario_id);
      seen.add(r.scenario_id);
      return { key: r.key, label: r.title, finishedAt: when(r.finished_at), latest };
    });
}
