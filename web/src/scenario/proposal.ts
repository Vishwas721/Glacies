// A draft scenario drawn on the map before it is simulated: the routes it removes and changes,
// along their real stop patterns, and the routes it adds, through the stops picked.

import type { LonLat, RouteDetail, RouteSummary } from "../api/types";
import type { ChangeLine } from "../compare/layers";
import { type Draft, routeKey } from "./draft";

/** Route indices whose stop patterns the drawing needs. */
export function draftRouteIdx(draft: Draft, routes: RouteSummary[]): number[] {
  const keys = new Set([...draft.removed, ...Object.keys(draft.headway)]);
  return routes.filter((r) => keys.has(routeKey(r))).map((r) => r.route_idx);
}

export function draftLines(
  draft: Draft,
  details: (RouteDetail | undefined)[],
  stops: ReadonlyMap<string, LonLat>,
): ChangeLine[] {
  const lines: ChangeLine[] = [];
  for (const detail of details) {
    if (!detail) continue;
    const key = routeKey(detail.route);
    const removed = draft.removed.includes(key);
    const factor = draft.headway[key];
    if (!removed && (factor === undefined || factor === 1)) continue;
    const name = detail.route.short_name ?? detail.route.route_id;
    for (const p of detail.features) {
      lines.push({
        mutationIdx: -1,
        kind: removed ? "removed" : "modified",
        name,
        path: p.geometry.coordinates,
      });
    }
  }
  // A route added without a feed names stops by id alone, as the scenario schema allows when
  // the id is unique across feeds.
  const byId = new Map<string, LonLat | null>();
  for (const [key, coords] of stops) {
    const id = key.slice(key.indexOf(":") + 1);
    byId.set(id, byId.has(id) ? null : coords);
  }
  for (const r of draft.added) {
    const find = (id: string) => (r.feed ? stops.get(`${r.feed}:${id}`) : byId.get(id));
    const along = (ids: string[]) =>
      ids.map(find).filter((c): c is LonLat => c !== undefined && c !== null);
    const path = along(r.stops);
    if (path.length > 1)
      lines.push({ mutationIdx: -1, kind: "added", name: r.name ?? r.route_id, path });
    if (!r.one_way && r.return_stops) {
      const back = along(r.return_stops);
      if (back.length > 1)
        lines.push({ mutationIdx: -1, kind: "added", name: r.name ?? r.route_id, path: back });
    }
  }
  return lines;
}
