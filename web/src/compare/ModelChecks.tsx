// How far to trust the loads on screen: the assignment against observed metro entries and the
// share of bus riders on segments loaded past what could board (soft capacity, ADR 0018).

import type { Checks } from "../api/types";
import { Field } from "../ui/Quantity";

const SET_LABELS: Record<string, string> = {
  training: "Training stations",
  held_out: "Held-out stations",
};

export function ModelChecks({ checks }: { checks: Checks }) {
  const f = checks.fields;
  const scored = checks.station_fits.filter((s) => s.set in SET_LABELS);
  const excluded = checks.station_fits.filter((s) => !(s.set in SET_LABELS));
  const over = checks.bus_load_bands.at(-1);
  return (
    <section className="card" aria-label="Model checks">
      <h3>How far to trust the loads</h3>
      {scored.length > 0 && (
        <table className="metrics" aria-label="Metro entries against observed">
          <tbody>
            {scored.map((s) => (
              <tr key={s.set}>
                <th scope="row">
                  {SET_LABELS[s.set]} (<Field value={s.stations} info={f.stations} />)
                </th>
                <td>
                  <Field value={s.level_ratio} info={f.level_ratio} />× observed entries
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {excluded.length > 0 && (
        <p className="note">
          {excluded.map((s) => `${s.stations} ${s.set} stations`).join(", ")} are not scored.
        </p>
      )}
      {over && (
        <p>
          <Field value={over.segment_share} info={f.segment_share} /> of peak bus segments (
          {checks.report_window[0]}–{checks.report_window[1]}) run above 1.5× design capacity and
          carry <Field value={over.passenger_share} info={f.passenger_share} /> of bus passengers.
        </p>
      )}
      <p className="note">
        Capacity is soft: the model lets riders exceed what could board, so these corridors show
        where demand piles up rather than real loads.
      </p>
    </section>
  );
}
