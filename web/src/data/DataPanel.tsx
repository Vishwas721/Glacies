// The Data mode: every source the city is built from, with its licence and label, which
// pipeline outputs exist, and what the four data-nature labels mean (CLAUDE.md rule 4).

import type { CityDetail, Nature } from "../api/types";
import { NatureBadge } from "../ui/Quantity";

const KIND: Record<string, string> = {
  gtfs: "Timetable (GTFS)",
  ridership: "Metro ridership",
  buildings: "Building footprints",
  osm_pbf: "OpenStreetMap",
  landcover_raster: "Land cover",
  population_raster: "Population",
};

export function Sources({ city }: { city: CityDetail }) {
  return (
    <section className="card" aria-label="Sources">
      <h3>Sources</h3>
      <ul className="sources">
        {city.sources.map((s) => (
          <li key={s.id}>
            <p className="source-kind">
              {KIND[s.kind] ?? s.kind} <NatureBadge nature={s.nature} />
            </p>
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.source}
            </a>
            <p className="source-meta mono">
              {s.license} ·{" "}
              {s.verified ? "URL and licence checked by hand" : "licence seen only second-hand"}
            </p>
          </li>
        ))}
      </ul>
      <p className="note">
        Raw downloads are archived with a manifest and validated before the engine reads them
        (data/README.md).
      </p>
    </section>
  );
}

export function Outputs({ city }: { city: CityDetail }) {
  return (
    <section className="card" aria-label="Pipeline outputs">
      <h3>Built outputs</h3>
      <ul className="outputs">
        {city.outputs.map((o) => (
          <li key={o.name} data-available={o.available}>
            <span className="output-mark" aria-hidden="true">
              {o.available ? "●" : "○"}
            </span>
            <span>{o.name}</span>
            <span className="mono muted">
              {o.available ? "built" : <code>uv run {o.command}</code>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const NATURES: { nature: Nature; text: string }[] = [
  {
    nature: "observed",
    text: "Read from a dataset as published: the timetable, stop locations, metro gate counts.",
  },
  {
    nature: "estimated",
    text: "A model input built from data: residents from the population raster, the employment proxy from buildings and job POIs. Never a count.",
  },
  {
    nature: "simulated",
    text: "Computed by Glacies: travel times, accessibility, assigned riders, crowding. As good as the inputs and the model.",
  },
  {
    nature: "assumed",
    text: "A parameter someone chose: vehicle capacities, a new route's speed, the edge buffer, the percentiles.",
  },
];

export function NatureKey() {
  return (
    <section className="card" aria-label="Data labels">
      <h3>The four labels</h3>
      <dl className="nature-key">
        {NATURES.map((n) => (
          <div key={n.nature}>
            <dt>
              <NatureBadge nature={n.nature} />
            </dt>
            <dd>{n.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function ModelSettings({ city }: { city: CityDetail }) {
  const a = city.accessibility;
  return (
    <section className="card" aria-label="Model settings">
      <h3>Settings in use</h3>
      <dl className="facts">
        <div>
          <dt>Timetable day</dt>
          <dd className="mono">{city.service_date ?? "unknown"}</dd>
        </div>
        <div>
          <dt>Time zone</dt>
          <dd className="mono">{city.timezone}</dd>
        </div>
        <div>
          <dt>Departure window</dt>
          <dd className="mono">
            {city.window[0]}–{city.window[1]}
          </dd>
        </div>
        <div>
          <dt>Travel-time thresholds</dt>
          <dd className="mono">{a.thresholds_min.map((t) => `${t}`).join(" · ")} min</dd>
        </div>
        <div>
          <dt>Percentiles over departures</dt>
          <dd className="mono">{a.percentiles.map((p) => `p${p}`).join(" · ")}</dd>
        </div>
        <div>
          <dt>Headline</dt>
          <dd className="mono">
            {a.headline_threshold_min} min at p{a.headline_percentile}
          </dd>
        </div>
      </dl>
      <p className="note">
        These are <NatureBadge nature="assumed" /> choices from the city's configuration (cities/
        {city.id}/city.toml).
      </p>
    </section>
  );
}
