// Finished scenario results (listed from disk by the API) as choices to compare with.

import type { ResultSummary } from "../api/types";

export interface ResultChoice {
  key: string;
  label: string;
}

/** Results with a comparison against the baseline; older cache entries without one are left out. */
export function comparableResults(results: ResultSummary[]): ResultChoice[] {
  return results
    .filter((r) => r.compared)
    .map((r) => ({
      key: r.key,
      label: `${r.scenario_id} (${r.finished_at.slice(0, 16).replace("T", " ")} UTC)`,
    }));
}
