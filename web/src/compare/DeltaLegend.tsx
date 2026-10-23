// Legend of the accessibility change map: the classes of `glacies scenario compare`.

import type { FieldInfo } from "../api/types";
import { toCss } from "../map/colours";
import { NatureBadge } from "../ui/Quantity";
import { DELTA_BREAKS, GAIN, LOSS } from "./layers";

const pp = (x: number) => `${(x * 100).toLocaleString("en", { maximumFractionDigits: 2 })} pp`;

export function DeltaLegend({ info }: { info: FieldInfo | undefined }) {
  const [low, high] = DELTA_BREAKS as [number, number];
  const classes = [`< ${pp(low)}`, `${pp(low)}–${pp(high)}`, `≥ ${pp(high)}`];
  return (
    <div className="legend" aria-label="Legend">
      <table className="delta-legend">
        <tbody>
          {classes.map((label, i) => (
            <tr key={label}>
              <td>
                <span className="swatch" style={{ background: toCss(GAIN[i]!) }} /> gain
              </td>
              <td>
                <span className="swatch" style={{ background: toCss(LOSS[i]!) }} /> loss
              </td>
              <td>{label}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Change in the share of the city's estimated jobs reachable, scenario minus baseline{" "}
        {info && <NatureBadge nature={info.nature} />}. Unchanged zones are not drawn.
      </p>
    </div>
  );
}
