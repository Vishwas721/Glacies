// The scenario being edited, and its conversion to and from the scenario JSON document.
// A route is keyed by feed and route_id, as scenario files reference it.

import type { AddRoute, Mutation, RouteSummary, Scenario } from "../api/types";

export interface Draft {
  scenarioId: string;
  title: string;
  description: string;
  removed: string[]; // route keys
  headway: Record<string, number>; // route key -> headway factor (0.5 = twice as often)
  added: AddRoute[];
}

export const routeKey = (r: Pick<RouteSummary, "feed" | "route_id">) => `${r.feed}:${r.route_id}`;

export const emptyDraft = (): Draft => ({
  scenarioId: "",
  title: "",
  description: "",
  removed: [],
  headway: {},
  added: [],
});

function split(key: string): { feed: string; route_id: string } {
  const at = key.indexOf(":");
  return { feed: key.slice(0, at), route_id: key.slice(at + 1) };
}

/** Removals first, then headway changes, then new routes, each sorted for stable files. */
export function toScenario(draft: Draft): Scenario {
  const mutations: Mutation[] = [
    ...[...draft.removed].sort().map((key) => ({ type: "remove_route" as const, ...split(key) })),
    ...Object.keys(draft.headway)
      .filter((key) => !draft.removed.includes(key) && draft.headway[key] !== 1)
      .sort()
      .map((key) => ({
        type: "modify_headway" as const,
        ...split(key),
        headway_factor: draft.headway[key]!,
      })),
    ...draft.added,
  ];
  return {
    schema_version: 1,
    scenario_id: draft.scenarioId,
    title: draft.title,
    ...(draft.description ? { description: draft.description } : {}),
    mutations,
  };
}

/**
 * The draft for a saved scenario. Mutations the builder cannot show (a fixed headway, a time
 * window, a route given without its feed) are reported, not dropped silently.
 */
export function fromScenario(
  scenario: Scenario,
  routes: RouteSummary[],
): { draft: Draft; unsupported: string[] } {
  const draft: Draft = {
    ...emptyDraft(),
    scenarioId: scenario.scenario_id,
    title: scenario.title,
    description: scenario.description ?? "",
  };
  const unsupported: string[] = [];
  const keyOf = (routeId: string, feed?: string) => {
    if (feed) return `${feed}:${routeId}`;
    const matches = routes.filter((r) => r.route_id === routeId);
    return matches.length === 1 ? routeKey(matches[0]!) : null;
  };
  for (const m of scenario.mutations) {
    if (m.type === "add_route") {
      draft.added.push(m);
      continue;
    }
    const key = keyOf(m.route_id, m.feed);
    if (key === null) {
      unsupported.push(`${m.type} ${m.route_id}: route not found in one feed`);
    } else if (m.type === "remove_route") {
      draft.removed.push(key);
    } else if (m.headway_factor !== undefined && !m.window && m.headway_secs === undefined) {
      draft.headway[key] = m.headway_factor;
    } else {
      unsupported.push(`modify_headway ${m.route_id}: fixed headways and windows`);
    }
  }
  return { draft, unsupported };
}
