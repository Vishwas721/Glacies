// The simulated morning flows as moving trails for the landing page: each stop pair's passengers
// in a 15-minute frame become one trail along the pair, leaving at a fixed point in the frame.
// The departure inside the frame and the speed only place the drawing; they are not model output.

import type { Flows, LonLat } from "../api/types";

export interface Trail {
  path: [LonLat, LonLat];
  /** Seconds after midnight at each end of the path. */
  timestamps: [number, number];
  metro: boolean;
  passengers: number;
}

export interface Trails {
  trails: Trail[];
  /** First departure and last arrival, seconds after midnight. */
  start: number;
  end: number;
}

/** Pairs carrying less than this in a frame are left out: residue no line width can show. */
const MIN_PASSENGERS = 1;
// Drawing speeds, metres per second: a city bus and a metro train between stops.
const SPEED = { bus: 5, metro: 11 };
const FRAME_S = 900;

export const clockSeconds = (hhmm: string): number => {
  const [h, m] = hhmm.split(":").map(Number);
  return (h ?? 0) * 3600 + (m ?? 0) * 60;
};

export const clockText = (seconds: number): string => {
  const m = Math.floor(seconds / 60);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

function metres([x1, y1]: LonLat, [x2, y2]: LonLat): number {
  const k = Math.PI / 180;
  const dx = (x2 - x1) * Math.cos(((y1 + y2) / 2) * k) * 111_320;
  const dy = (y2 - y1) * 110_540;
  return Math.hypot(dx, dy);
}

/** The box holding most trail ends (2nd to 98th percentile), leaving out far outliers. */
export function coreBox({ trails }: Trails): [number, number, number, number] | null {
  if (!trails.length) return null;
  const lng = trails.map((t) => t.path[0][0]).sort((a, b) => a - b);
  const lat = trails.map((t) => t.path[0][1]).sort((a, b) => a - b);
  const at = (xs: number[], q: number) => xs[Math.floor(q * (xs.length - 1))]!;
  return [at(lng, 0.02), at(lat, 0.02), at(lng, 0.98), at(lat, 0.98)];
}

/** A fixed offset in [0, 900) per pair, so the same pair leaves at the same point each frame. */
const offset = (pair: number) => (Math.imul(pair + 1, 2654435761) >>> 0) % FRAME_S;

export function trailsFromFlows(flows: Flows): Trails {
  const trails: Trail[] = [];
  let start = Infinity;
  let end = -Infinity;
  flows.frame_idx.forEach((f, i) => {
    const passengers = flows.passengers[i]!;
    if (passengers < MIN_PASSENGERS) return;
    const p = flows.pair_idx[i]!;
    const c = flows.pairs.coordinates[p]!;
    const from: LonLat = [c[0], c[1]];
    const to: LonLat = [c[2], c[3]];
    const metro = flows.pairs.mode[p] === "metro";
    const leave = clockSeconds(flows.frames[f]!.start) + offset(p);
    const arrive = leave + Math.max(30, metres(from, to) / (metro ? SPEED.metro : SPEED.bus));
    trails.push({ path: [from, to], timestamps: [leave, arrive], metro, passengers });
    start = Math.min(start, leave);
    end = Math.max(end, arrive);
  });
  return trails.length ? { trails, start, end } : { trails, start: 0, end: 0 };
}
