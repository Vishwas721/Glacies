// The What-If Lens divider: drag it (or use the arrow keys) to move the line between the
// baseline, drawn to its left, and the scenario, drawn to its right.

import { useRef } from "react";

import type { Lens } from "./MapView";

const MIN = 0.04;
const MAX = 0.96;
const clamp = (f: number) => Math.min(MAX, Math.max(MIN, f));

export function LensDivider({ lens }: { lens: Lens }) {
  const dragging = useRef(false);
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const box = e.currentTarget.parentElement!.getBoundingClientRect();
    lens.onFraction(clamp((e.clientX - box.left) / box.width));
  };
  return (
    <div
      className="lens"
      style={{ left: `${lens.fraction * 100}%` }}
      role="slider"
      tabIndex={0}
      aria-label="Lens divider: baseline to the left, scenario to the right"
      aria-valuemin={Math.round(MIN * 100)}
      aria-valuemax={Math.round(MAX * 100)}
      aria-valuenow={Math.round(lens.fraction * 100)}
      aria-valuetext={`${Math.round(lens.fraction * 100)} % from the left`}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={move}
      onPointerUp={() => (dragging.current = false)}
      onPointerCancel={() => (dragging.current = false)}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 0.1 : 0.02;
        if (e.key === "ArrowLeft") lens.onFraction(clamp(lens.fraction - step));
        if (e.key === "ArrowRight") lens.onFraction(clamp(lens.fraction + step));
      }}
    >
      <span className="lens-label lens-left">{lens.left}</span>
      <span className="lens-grip" aria-hidden="true">
        <svg viewBox="0 0 12 12">
          <path d="M4 3 1 6l3 3M8 3l3 3-3 3" />
        </svg>
      </span>
      <span className="lens-label lens-right">{lens.right}</span>
    </div>
  );
}
