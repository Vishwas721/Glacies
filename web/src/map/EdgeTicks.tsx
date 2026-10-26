// Longitude and latitude ticks along the top and left edges of the map (positions: ticks.ts).

import { type Ticks, tickLabel } from "./ticks";

export function EdgeTicks({ ticks }: { ticks: Ticks }) {
  return (
    <div className="edge-ticks" aria-hidden="true">
      {ticks.lng.map((t) => (
        <span key={`x${t.value.toFixed(4)}`} className="tick tick-x" style={{ left: t.x }}>
          {tickLabel(t.value, ticks.step, "E", "W")}
        </span>
      ))}
      {ticks.lat.map((t) => (
        <span key={`y${t.value.toFixed(4)}`} className="tick tick-y" style={{ top: t.y }}>
          {tickLabel(t.value, ticks.step, "N", "S")}
        </span>
      ))}
    </div>
  );
}
