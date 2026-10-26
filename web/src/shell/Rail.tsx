// The mode rail: the Glacies mark, the four modes, and the state of the services behind them.

import type { ReactNode } from "react";

import { type Mode, MODES } from "./modes";

const ICON: Record<Mode, ReactNode> = {
  // A survey crosshair.
  explore: (
    <>
      <circle cx="12" cy="12" r="6.5" />
      <path d="M12 2.5v5M12 16.5v5M2.5 12h5M16.5 12h5" />
    </>
  ),
  // Three stops joined, one being moved.
  design: (
    <>
      <circle cx="5" cy="18" r="2" />
      <circle cx="12" cy="8" r="2" />
      <circle cx="19" cy="15" r="2" strokeDasharray="2 1.6" />
      <path d="M6.2 16.3 10.8 9.7M13.6 9.3l3.8 4.2" />
    </>
  ),
  // A split frame: before | after.
  compare: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="1" />
      <path d="M12 2.5v19" />
      <path d="M6.5 15l3-4M14.5 15l3-6" />
    </>
  ),
  // Stacked layers of sources.
  data: (
    <>
      <path d="M12 3.5 20.5 8 12 12.5 3.5 8z" />
      <path d="M3.5 12 12 16.5 20.5 12M3.5 16 12 20.5 20.5 16" />
    </>
  ),
};

interface Props {
  mode: Mode;
  onMode: (mode: Mode) => void;
  /** One line per service, e.g. the API and the simulation queue. */
  status: { label: string; state: "ok" | "busy" | "down"; detail: string }[];
}

export function Rail({ mode, onMode, status }: Props) {
  return (
    <nav className="rail" aria-label="Modes">
      <div className="mark" aria-label="Glacies">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <polygon points="16,2.5 28,9.5 28,22.5 16,29.5 4,22.5 4,9.5" />
          <polygon points="16,9 22,12.5 22,19.5 16,23 10,19.5 10,12.5" />
        </svg>
      </div>
      <ul>
        {MODES.map((m) => (
          <li key={m.id}>
            <button
              type="button"
              className="rail-mode"
              aria-current={mode === m.id ? "page" : undefined}
              title={m.title}
              onClick={() => onMode(m.id)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                {ICON[m.id]}
              </svg>
              <span>{m.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <ul className="rail-status" aria-label="Services">
        {status.map((s) => (
          <li key={s.label} title={s.detail}>
            <span className={`dot dot-${s.state}`} aria-hidden="true" />
            <span>{s.label}</span>
            <span className="sr-only">: {s.detail}</span>
          </li>
        ))}
      </ul>
    </nav>
  );
}
