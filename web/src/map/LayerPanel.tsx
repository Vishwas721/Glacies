// Layer toggles and the legend of the zone layer shown (PRD §40).

import { Field } from "../ui/Quantity";
import { DeltaLegend } from "../compare/DeltaLegend";
import { LOAD_FACTOR_TOP } from "../compare/layers";
import { NatureBadge } from "../ui/Quantity";
import { toCss, viridis } from "./colours";
import type { LayerState, Legend, Loads, View, ZoneLayer } from "./layerState";

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
};

const LOAD_LABELS: Record<Loads, string> = {
  none: "None",
  crowding: "Peak-hour crowding",
  flows: "Flow playback",
};

const RAMP = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => toCss(viridis(t))).join(", ")})`;

interface Props {
  hasResult: boolean;
  state: LayerState;
  onChange: (state: LayerState) => void;
  percentiles: number[];
  thresholds: number[];
  legend: Legend | null;
}

export function LayerPanel({ hasResult, state, onChange, percentiles, thresholds, legend }: Props) {
  const set = (patch: Partial<LayerState>) => onChange({ ...state, ...patch });
  return (
    <section aria-label="Layers" className="card">
      <h3>Layers</h3>
      {hasResult && (
        <fieldset>
          <legend>Show</legend>
          {(Object.keys(VIEW_LABELS) as View[]).map((v) => (
            <label key={v} className="inline">
              <input
                type="radio"
                name="view"
                checked={state.view === v}
                onChange={() => set({ view: v })}
              />{" "}
              {VIEW_LABELS[v]}
            </label>
          ))}
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
      {hasResult && state.view === "change" && state.zones === "accessibility" ? (
        <DeltaLegend info={legend?.info} />
      ) : (
        legend &&
        state.zones !== "none" && (
          <div className="legend" aria-label="Legend">
            <div className="ramp" style={{ background: RAMP }} />
            <div className="ramp-labels">
              <Field value={0} info={legend.info} />
              <span>
                ≥ <Field value={legend.top} info={legend.info} />
              </span>
            </div>
            <p className="note">
              {legend.info?.description} Colours top out at the 98th percentile; low values are
              paler.
            </p>
          </div>
        )
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
      {state.loads !== "none" && (
        <div className="legend" aria-label="Load legend">
          <div className="ramp" style={{ background: RAMP }} />
          <div className="ramp-labels">
            <span>empty</span>
            <span>≥ {LOAD_FACTOR_TOP}× design capacity</span>
          </div>
          <p className="note">
            Load over design capacity <NatureBadge nature="simulated" />; capacities{" "}
            <NatureBadge nature="assumed" />.{" "}
            {state.view === "change" && "Loads show the scenario."}
          </p>
        </div>
      )}
    </section>
  );
}
