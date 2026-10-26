// Reading simulation records (ADR 0021) for the screen: times and stages as recorded.

import type { Simulation } from "../api/types";

const ACTIVE = new Set(["queued", "running"]);

export const isActive = (s: Simulation) => ACTIVE.has(s.status);

export const clock = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/** Elapsed time between two recorded timestamps, e.g. "5 min 2 s". */
export function duration(from: string, to: string): string {
  const s = Math.max(0, Math.round((Date.parse(to) - Date.parse(from)) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function stage(sim: Simulation): string {
  const p = sim.progress;
  if (sim.status === "queued") return "waiting for the worker";
  if (sim.status !== "running") return "";
  const step = p.stage_index === null ? "" : `${p.stage_index + 1}/${p.stages.length} `;
  return `${step}${p.message ?? p.stage ?? "starting"}`;
}
