// The dock under the map: long-running and time-based things (simulation runs, flow playback)
// that need width but should not cover the map. Collapsed it is a single bar of tabs.

import type { ReactNode } from "react";

export interface DockTab {
  id: string;
  label: string;
  /** A short state shown on the tab, e.g. "running". */
  hint?: string;
  content: ReactNode;
}

interface Props {
  tabs: DockTab[];
  active: string | null;
  open: boolean;
  onActive: (id: string) => void;
  onOpen: (open: boolean) => void;
}

export function Dock({ tabs, active, open, onActive, onOpen }: Props) {
  const current = tabs.find((t) => t.id === active) ?? tabs[0];
  return (
    <section className="dock" data-open={open} aria-label="Dock">
      <div className="dock-bar" role="tablist" aria-label="Dock tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={open && t.id === current?.id}
            className="dock-tab"
            onClick={() => {
              onActive(t.id);
              onOpen(!(open && t.id === current?.id));
            }}
          >
            {t.label}
            {t.hint && <span className="dock-hint">{t.hint}</span>}
          </button>
        ))}
        <button
          type="button"
          className="dock-toggle"
          aria-expanded={open}
          aria-label={open ? "Collapse the dock" : "Expand the dock"}
          onClick={() => onOpen(!open)}
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d={open ? "M2 4.5 6 8.5l4-4" : "M2 7.5 6 3.5l4 4"} />
          </svg>
        </button>
      </div>
      {open && current && (
        <div className="dock-body" role="tabpanel" aria-label={current.label}>
          {current.content}
        </div>
      )}
    </section>
  );
}
