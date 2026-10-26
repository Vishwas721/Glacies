// Routes with a toggle (in service / removed) and a frequency change (PRD §39 left panel).
// Bengaluru has 4,371 routes, so the list shows the routes changed so far plus search matches.

import { useMemo, useState } from "react";

import type { RouteList as RouteListData, RouteSummary } from "../api/types";
import { Field } from "../ui/Quantity";
import { type Draft, routeKey } from "./draft";

const MAX_MATCHES = 40;
// Headway factors: 0.5 halves the time between trips (twice as often).
const FACTORS = [0.5, 0.75, 1, 1.5, 2] as const;
const factorLabel = (f: number) =>
  f === 1 ? "as today" : `${(1 / f).toLocaleString("en", { maximumFractionDigits: 2 })}× as often`;

interface Props {
  data: RouteListData;
  draft: Draft;
  onChange: (draft: Draft) => void;
  selected: number | null;
  onSelect: (routeIdx: number | null) => void;
  /** Text to search for, e.g. a route picked on the map; `n` changes to search again. */
  seed?: { text: string; n: number };
}

const routeName = (r: RouteSummary) => r.short_name ?? r.route_id;

export function RouteList({ data, draft, onChange, selected, onSelect, seed }: Props) {
  const [search, setSearch] = useState("");
  // A new seed replaces the search once (React's "adjust state on a prop change" pattern).
  const [seenSeed, setSeenSeed] = useState(seed);
  if (seed !== seenSeed) {
    setSeenSeed(seed);
    if (seed) setSearch(seed.text);
  }
  const changed = useMemo(() => {
    const keys = new Set([...draft.removed, ...Object.keys(draft.headway)]);
    return data.routes.filter((r) => keys.has(routeKey(r)));
  }, [data.routes, draft.removed, draft.headway]);
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return data.routes
      .filter((r) =>
        [r.short_name, r.long_name, r.route_id].some((t) => t?.toLowerCase().includes(q)),
      )
      .slice(0, MAX_MATCHES);
  }, [data.routes, search]);

  const toggle = (r: RouteSummary, inService: boolean) => {
    const key = routeKey(r);
    const removed = draft.removed.filter((k) => k !== key);
    onChange({ ...draft, removed: inService ? removed : [...removed, key] });
  };
  const setFactor = (r: RouteSummary, factor: number) => {
    const headway = { ...draft.headway };
    if (factor === 1) delete headway[routeKey(r)];
    else headway[routeKey(r)] = factor;
    onChange({ ...draft, headway });
  };

  const row = (r: RouteSummary) => {
    const key = routeKey(r);
    const removed = draft.removed.includes(key);
    return (
      <li key={key} className={selected === r.route_idx ? "route selected" : "route"}>
        <label className="route-name">
          <input
            type="checkbox"
            checked={!removed}
            aria-label={`${routeName(r)} in service`}
            onChange={(e) => toggle(r, e.target.checked)}
          />{" "}
          <button type="button" className="link" onClick={() => onSelect(r.route_idx)}>
            {routeName(r)}
          </button>{" "}
          <span className="muted">{r.mode}</span>
        </label>
        <div className="route-detail">
          <Field value={r.window_trips} info={data.fields.window_trips} />{" "}
          <span className="muted">
            {data.window.start}–{data.window.end}
          </span>
        </div>
        <select
          aria-label={`${routeName(r)} frequency`}
          disabled={removed}
          value={draft.headway[key] ?? 1}
          onChange={(e) => setFactor(r, Number(e.target.value))}
        >
          {FACTORS.map((f) => (
            <option key={f} value={f}>
              {factorLabel(f)}
            </option>
          ))}
        </select>
      </li>
    );
  };

  return (
    <section aria-label="Routes" className="card">
      <h3>Routes</h3>
      {changed.length > 0 && (
        <>
          <h4>Changed</h4>
          <ul className="routes">{changed.map(row)}</ul>
        </>
      )}
      <input
        type="search"
        placeholder="Find a route (e.g. 500-D)"
        aria-label="Find a route"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ul className="routes">{matches.filter((r) => !changed.includes(r)).map(row)}</ul>
      {search && matches.length === MAX_MATCHES && (
        <p className="note">First {MAX_MATCHES} matches; type more to narrow.</p>
      )}
    </section>
  );
}
