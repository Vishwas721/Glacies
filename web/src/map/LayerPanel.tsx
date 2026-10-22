// Layer toggles and the legend of the zone layer shown (PRD §40).

import { Field } from "../ui/Quantity";
import { toCss, viridis } from "./colours";
import type { LayerState, Legend, ZoneLayer } from "./layerState";

const ZONE_LABELS: Record<ZoneLayer, string> = {
  none: "None",
  population: "Population",
  employment: "Estimated employment",
  accessibility: "Accessibility to estimated jobs",
};

interface Props {
  state: LayerState;
  onChange: (state: LayerState) => void;
  percentiles: number[];
  thresholds: number[];
  legend: Legend | null;
}

export function LayerPanel({ state, onChange, percentiles, thresholds, legend }: Props) {
  const set = (patch: Partial<LayerState>) => onChange({ ...state, ...patch });
  return (
    <section aria-label="Layers" className="card">
      <h3>Layers</h3>
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
      {legend && state.zones !== "none" && (
        <div className="legend" aria-label="Legend">
          <div
            className="ramp"
            style={{
              background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1]
                .map((t) => toCss(viridis(t)))
                .join(", ")})`,
            }}
          />
          <div className="ramp-labels">
            <Field value={0} info={legend.info} />
            <span>
              ≥ <Field value={legend.top} info={legend.info} />
            </span>
          </div>
          <p className="note">{legend.info?.description} Colours top out at the 98th percentile.</p>
        </div>
      )}
    </section>
  );
}
