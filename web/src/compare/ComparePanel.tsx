// Before and after (PRD §31, §39, §73 steps 5-7): the comparison metrics, the routes the
// scenario changed and where riders moved. Every value carries its row's data nature.

import { useChanges, useMetrics } from "../api/queries";
import type { Changes, MetricRow } from "../api/types";
import { NatureBadge, Quantity } from "../ui/Quantity";
import { format, formatDelta } from "../ui/format";
import { KIND_COLOUR } from "./layers";
import { toCss } from "../map/colours";

// The PRD §39 panel leads with these; the rest sit under "All metrics".
const HEADLINE = [
  "Assignment: travel time per transit trip",
  "Assignment: waiting per transit trip",
  "Assignment: transfers per transit trip",
  "Estimated jobs reachable within 45 min (p50, population-weighted)",
  "Assignment: crowding, peak passenger-km above design capacity",
  "Assignment: metro gate entries",
];

function Row({ row }: { row: MetricRow }) {
  return (
    <tr>
      <th scope="row">{row.metric.replace(/^Assignment: /, "")}</th>
      <td>
        {format(row.baseline, row.unit)} → {format(row.scenario, row.unit)}
      </td>
      <td>{formatDelta(row.delta, row.unit)}</td>
      <td>
        <NatureBadge nature={row.nature} />
      </td>
    </tr>
  );
}

function MetricsTable({ rows }: { rows: MetricRow[] }) {
  const headline = HEADLINE.map((m) => rows.find((r) => r.metric === m)).filter(
    (r): r is MetricRow => r !== undefined,
  );
  const rest = rows.filter((r) => !HEADLINE.includes(r.metric));
  const table = (list: MetricRow[], label: string) => (
    <table className="metrics" aria-label={label}>
      <tbody>
        {list.map((r) => (
          <Row key={r.metric} row={r} />
        ))}
      </tbody>
    </table>
  );
  return (
    <>
      {table(headline, "Headline metrics")}
      <details>
        <summary>All metrics ({rows.length})</summary>
        {table(rest, "All metrics")}
      </details>
    </>
  );
}

function ChangesList({ changes }: { changes: Changes }) {
  const f = changes.fields;
  return (
    <>
      <h4>Routes changed</h4>
      <ul className="routes" aria-label="Routes changed">
        {changes.routes.map((r) => (
          <li key={r.mutation_idx} className="route">
            <span className="swatch" style={{ background: toCss(KIND_COLOUR[r.kind]) }} />{" "}
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
      {changes.largest_boardings_changes.length > 0 && (
        <>
          <h4>Where riders moved</h4>
          <table className="metrics" aria-label="Where riders moved">
            <tbody>
              {changes.largest_boardings_changes.map((d) => (
                <tr key={d.route_idx}>
                  <th scope="row">
                    {d.name ?? d.route_idx} <span className="muted">{d.mode}</span>
                  </th>
                  <td>{formatDelta(d.boardings_delta, "count")} boardings</td>
                  <td>
                    <NatureBadge nature={f.boardings_delta!.nature} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

export function ComparePanel({ city, result }: { city: string; result: string }) {
  const metrics = useMetrics(city, result);
  const changes = useChanges(city, result);
  return (
    <section className="card" aria-label="Comparison">
      <h3>Scenario vs baseline</h3>
      <p className="note">
        Same AM-peak demand on both networks (ADR 0019): changes come from route choice, waiting and
        crowding, not from new riders.
      </p>
      {metrics.error && <p className="error">{metrics.error.message}</p>}
      {metrics.data && <MetricsTable rows={metrics.data.rows} />}
      {changes.data && <ChangesList changes={changes.data} />}
    </section>
  );
}
