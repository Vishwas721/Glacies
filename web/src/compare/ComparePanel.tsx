// The impact ledger (PRD §31, §39, §73 steps 5-7): baseline and scenario side by side for the
// headline metrics, with the change, whether it is an improvement and what the metric measures;
// then the routes the scenario changed and where riders moved. Every value carries its badge.

import { useChanges, useMetrics } from "../api/queries";
import type { Changes, MetricRow } from "../api/types";
import { NatureBadge, Quantity } from "../ui/Quantity";
import { format, formatDelta, formatPair } from "../ui/format";
import { DEFINITIONS, reading } from "./ledger";
import { KIND_CSS } from "./layers";

// The PRD §39 panel leads with these; the rest sit under "All metrics".
const HEADLINE = [
  "Assignment: travel time per transit trip",
  "Assignment: waiting per transit trip",
  "Assignment: transfers per transit trip",
  "Estimated jobs reachable within 45 min (p50, population-weighted)",
  "Assignment: crowding, peak passenger-km above design capacity",
  "Assignment: metro gate entries",
];

const name = (metric: string) => metric.replace(/^Assignment: /, "");

function Entry({ row, define }: { row: MetricRow; define: boolean }) {
  const [before, after] = formatPair(row.baseline, row.scenario, row.unit);
  const read = reading(row.metric, row.delta);
  const definition = define ? DEFINITIONS[row.metric] : undefined;
  return (
    <li className="ledger-row" data-reading={read ?? "neutral"}>
      <div className="ledger-name">
        <span>{name(row.metric)}</span> <NatureBadge nature={row.nature} />
      </div>
      <div className="ledger-values">
        <span className="ledger-pair">
          {before} → {after}
        </span>
        <span className="ledger-delta">{formatDelta(row.delta, row.unit)}</span>
        <span className="ledger-reading">{read ?? "no better side"}</span>
      </div>
      {definition && <p className="ledger-def">{definition}</p>}
    </li>
  );
}

function Ledger({ rows }: { rows: MetricRow[] }) {
  const headline = HEADLINE.map((m) => rows.find((r) => r.metric === m)).filter(
    (r): r is MetricRow => r !== undefined,
  );
  const rest = rows.filter((r) => !HEADLINE.includes(r.metric));
  return (
    <>
      <ul className="ledger" aria-label="Headline metrics">
        {headline.map((r) => (
          <Entry key={r.metric} row={r} define />
        ))}
      </ul>
      <details>
        <summary>All metrics ({rows.length})</summary>
        <ul className="ledger ledger-compact" aria-label="All metrics">
          {rest.map((r) => (
            <Entry key={r.metric} row={r} define={false} />
          ))}
        </ul>
      </details>
    </>
  );
}

function ChangesList({ changes }: { changes: Changes }) {
  const f = changes.fields;
  const moved = changes.largest_boardings_changes;
  const top = Math.max(1, ...moved.map((d) => Math.abs(d.boardings_delta)));
  return (
    <>
      <h4>Routes changed</h4>
      <ul className="routes" aria-label="Routes changed">
        {changes.routes.map((r) => (
          <li key={r.mutation_idx} className="route">
            <span className="swatch" style={{ background: KIND_CSS[r.kind] }} />{" "}
            <strong>{r.name ?? r.route_id}</strong> {r.kind}
            {r.trips_added > 0 && (
              <>
                {" "}
                · +<Quantity value={r.trips_added} nature={f.trips_added!.nature} unit="trips" />
              </>
            )}
            {r.trips_removed > 0 && (
              <>
                {" "}
                · −
                <Quantity value={r.trips_removed} nature={f.trips_removed!.nature} unit="trips" />
              </>
            )}
            {r.boardings_baseline !== null && r.boardings_scenario !== null && (
              <div className="route-detail">
                boardings {format(r.boardings_baseline, "count")} →{" "}
                {format(r.boardings_scenario, "count")}{" "}
                <NatureBadge nature={f.boardings_scenario!.nature} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {moved.length > 0 && (
        <>
          <h4>Where riders moved</h4>
          <table className="metrics moved" aria-label="Where riders moved">
            <tbody>
              {moved.map((d) => (
                <tr key={d.route_idx}>
                  <th scope="row">
                    {d.name ?? d.route_idx} <span className="muted">{d.mode}</span>
                  </th>
                  <td className="moved-bar" aria-hidden="true">
                    <span
                      data-sign={d.boardings_delta > 0 ? "+" : "−"}
                      style={{ width: `${(50 * Math.abs(d.boardings_delta)) / top}%` }}
                    />
                  </td>
                  <td>{formatDelta(d.boardings_delta, "count")} boardings</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            Boardings per route <NatureBadge nature={f.boardings_delta!.nature} />: riders moving
            between routes, not new riders.
          </p>
        </>
      )}
    </>
  );
}

export function ComparePanel({
  city,
  result,
  title,
}: {
  city: string;
  result: string;
  title?: string;
}) {
  const metrics = useMetrics(city, result);
  const changes = useChanges(city, result);
  return (
    <section className="card ledger-card" aria-label="Comparison">
      <p className="eyebrow">Impact ledger · scenario vs baseline</p>
      {title && <h3>{title}</h3>}
      <p className="note">
        Same AM-peak demand on both networks (ADR 0019): changes come from route choice, waiting and
        crowding, not from new riders.
      </p>
      {metrics.isPending && <p className="note">Loading the metrics…</p>}
      {metrics.error && <p className="error">{metrics.error.message}</p>}
      {metrics.data && <Ledger rows={metrics.data.rows} />}
      {changes.data && <ChangesList changes={changes.data} />}
    </section>
  );
}
