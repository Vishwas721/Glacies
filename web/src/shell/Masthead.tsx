// The strip above the map: which city and timetable, how big the network is, and which network
// the map is showing right now (baseline, a scenario, or the change between them).

import type { CityDetail, FieldInfo } from "../api/types";
import { Field, Quantity } from "../ui/Quantity";

export interface NetworkSize {
  routes: number;
  stops: number | null;
  windowTrips: number;
  windowTripsInfo: FieldInfo | undefined;
}

interface Props {
  city: CityDetail;
  size: NetworkSize | null;
  /** What the map shows, e.g. "Baseline" or "Change · East Bengaluru package". */
  showing: string;
  inspectorOpen: boolean;
  onInspector: (open: boolean) => void;
}

export function Masthead({ city, size, showing, inspectorOpen, onInspector }: Props) {
  return (
    <header className="masthead">
      <div className="masthead-city">
        <h1>{city.name}</h1>
        <p className="masthead-meta">
          timetable of {city.service_date ?? "unknown date"} · AM window {city.window[0]}–
          {city.window[1]} · {city.timezone}
        </p>
      </div>
      {size && (
        <dl className="masthead-stats" aria-label="Network size">
          <div>
            <dt>routes</dt>
            <dd>
              <Quantity value={size.routes} nature="observed" unit="count" />
            </dd>
          </div>
          {size.stops !== null && (
            <div>
              <dt>stops</dt>
              <dd>
                <Quantity value={size.stops} nature="observed" unit="count" />
              </dd>
            </div>
          )}
          <div>
            <dt>
              trips {city.window[0]}–{city.window[1]}
            </dt>
            <dd>
              <Field value={size.windowTrips} info={size.windowTripsInfo} />
            </dd>
          </div>
        </dl>
      )}
      <p className="masthead-showing" aria-live="polite">
        <span>Map shows</span> {showing}
      </p>
      <button
        type="button"
        className="masthead-inspector"
        aria-pressed={inspectorOpen}
        aria-label={inspectorOpen ? "Hide the inspector" : "Show the inspector"}
        onClick={() => onInspector(!inspectorOpen)}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1.5" y="2.5" width="13" height="11" rx="1" />
          <path d="M10 2.5v11" />
        </svg>
      </button>
    </header>
  );
}
