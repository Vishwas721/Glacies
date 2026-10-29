// The legends of the layers on the map, drawn over its lower-left corner: the zone layer
// (viridis levels or the change classes) and passenger loads.

import { DeltaLegend } from "../compare/DeltaLegend";
import { KIND_CSS, LOAD_FACTOR_TOP } from "../compare/layers";
import { Field, NatureBadge } from "../ui/Quantity";
import { toCss, viridis } from "./colours";
import type { LayerState, Legend } from "./layerState";

const RAMP = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => toCss(viridis(t))).join(", ")})`;

interface Props {
  state: LayerState;
  /** Which network the layers show; "change" draws the change classes. */
  view: LayerState["view"];
  legend: Legend | null;
  /** Zones are raised by their value. */
  relief?: boolean;
  /** Routes a scenario or a draft changes are drawn. */
  routeChanges?: boolean;
}

export function MapLegend({ state, view, legend, relief = false, routeChanges = false }: Props) {
  const change = view === "change" && state.zones === "accessibility";
  const zones = state.zones !== "none" && (change || legend);
  if (!zones && state.loads === "none" && !routeChanges) return null;
  return (
    <div className="map-legend">
      {routeChanges && (
        <ul className="route-key" aria-label="Route changes">
          <li>
            <span className="line line-removed" style={{ color: KIND_CSS.removed }} />
            removed
          </li>
          <li>
            <span className="line" style={{ color: KIND_CSS.modified }} />
            runs more or less often
          </li>
          <li>
            <span className="line line-added" style={{ color: KIND_CSS.added }} />
            added
          </li>
        </ul>
      )}
      {change ? (
        <DeltaLegend info={legend?.info} />
      ) : (
        legend &&
        state.zones !== "none" && (
          <div className="legend" aria-label="Legend">
            <p className="legend-title">{legend.info?.description}</p>
            <div className="ramp" style={{ background: RAMP }} />
            <div className="ramp-labels">
              <Field value={0} info={legend.info} />
              <span>
                ≥ <Field value={legend.top} info={legend.info} />
              </span>
            </div>
            <p className="note">
              Colours top out at the 98th percentile; low values are paler.
              {relief && " Height shows the same value as colour, flat at zero."}
            </p>
          </div>
        )
      )}
      {state.loads !== "none" && (
        <div className="legend" aria-label="Load legend">
          <p className="legend-title">
            Load over design capacity <NatureBadge nature="simulated" />
          </p>
          <div className="ramp" style={{ background: RAMP }} />
          <div className="ramp-labels">
            <span>empty</span>
            <span>≥ {LOAD_FACTOR_TOP}× design capacity</span>
          </div>
          <p className="note">
            Capacities <NatureBadge nature="assumed" />; width is passengers.
            {(view === "change" || (view === "split" && state.loads === "flows")) &&
              " Loads show the scenario."}
          </p>
        </div>
      )}
    </div>
  );
}
