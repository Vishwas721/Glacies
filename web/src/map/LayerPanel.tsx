// Layer toggles (PRD §40); their legend is drawn on the map (MapLegend).

import type { LayerState, Loads, View, ZoneLayer } from "./layerState";

const ZONE_LABELS: Record<ZoneLayer, string> = {
  none: "None",
  population: "Population",
  employment: "Estimated employment",
  accessibility: "Accessibility to estimated jobs",
};

const VIEW_LABELS: Record<View, string> = {
  baseline: "Baseline",
  scenario: "Scenario",
  change: "Change",
  split: "Lens",
};

const VIEW_HINTS: Record<View, string> = {
  baseline: "Today's network",
  scenario: "The network with the scenario's changes",
  change: "Scenario minus baseline, in the comparison report's classes",
  split: "Baseline left of a divider you can drag, scenario right of it",
};

const LOAD_LABELS: Record<Loads, string> = {
  none: "None",
  crowding: "Peak-hour crowding",
  flows: "Flow playback",
};

interface Props {
  hasResult: boolean;
  state: LayerState;
  onChange: (state: LayerState) => void;
  percentiles: number[];
  thresholds: number[];
}

export function LayerPanel({ hasResult, state, onChange, percentiles, thresholds }: Props) {
  const set = (patch: Partial<LayerState>) => onChange({ ...state, ...patch });
  return (
    <section aria-label="Layers" className="card">
      <h3>Layers</h3>
      {hasResult && (
        <fieldset className="segmented-field">
          <legend>Show</legend>
          <div className="segmented">
            {(Object.keys(VIEW_LABELS) as View[]).map((v) => (
              <label key={v} title={VIEW_HINTS[v]}>
                <input
                  type="radio"
                  name="view"
                  checked={state.view === v}
                  onChange={() => set({ view: v })}
                />
                <span>{VIEW_LABELS[v]}</span>
              </label>
            ))}
          </div>
          <p className="note">{VIEW_HINTS[state.view]}.</p>
        </fieldset>
      )}
      <label>
        <input
          type="checkbox"
          checked={state.network}
          onChange={(e) => set({ network: e.target.checked })}
        />{" "}
        Bus and metro network
      </label>
      <label>
        <input
          type="checkbox"
          checked={state.stops}
          onChange={(e) => set({ stops: e.target.checked })}
        />{" "}
        Stops
      </label>
      <fieldset>
        <legend>Zones</legend>
        {(Object.keys(ZONE_LABELS) as ZoneLayer[]).map((z) => (
          <label key={z}>
            <input
              type="radio"
              name="zones"
              checked={state.zones === z}
              onChange={() => set({ zones: z })}
            />{" "}
            {ZONE_LABELS[z]}
          </label>
        ))}
      </fieldset>
      {state.zones === "accessibility" && (
        <div className="row">
          <label>
            Within{" "}
            <select
              aria-label="Threshold"
              value={state.thresholdMin}
              onChange={(e) => set({ thresholdMin: Number(e.target.value) })}
            >
              {thresholds.map((t) => (
                <option key={t} value={t}>
                  {t} min
                </option>
              ))}
            </select>
          </label>{" "}
          <label>
            at{" "}
            <select
              aria-label="Percentile"
              value={state.percentile}
              onChange={(e) => set({ percentile: Number(e.target.value) })}
            >
              {percentiles.map((p) => (
                <option key={p} value={p}>
                  p{p}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <fieldset>
        <legend>Passenger loads</legend>
        {(Object.keys(LOAD_LABELS) as Loads[]).map((l) => (
          <label key={l}>
            <input
              type="radio"
              name="loads"
              checked={state.loads === l}
              onChange={() => set({ loads: l })}
            />{" "}
            {LOAD_LABELS[l]}
          </label>
        ))}
      </fieldset>
    </section>
  );
}
