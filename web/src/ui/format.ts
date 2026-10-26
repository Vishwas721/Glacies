// Number formatting for labelled quantities; the unit names are the API's `fields` units.

const SUFFIX: Record<string, string> = { minutes: "min", index: "" };

function suffix(unit: string | null): string {
  if (!unit || ["count", "share", "ratio"].includes(unit)) return "";
  const s = SUFFIX[unit] ?? unit;
  return s ? ` ${s}` : "";
}

/** `digits` fixes the number of decimals, for values that must be told apart. */
export function format(value: number, unit: string | null, digits?: number): string {
  const fixed = (d: number) => ({ minimumFractionDigits: d, maximumFractionDigits: d });
  const opts = (fallback: number) =>
    digits === undefined ? { maximumFractionDigits: fallback } : fixed(digits);
  if (unit === "share") return `${(value * 100).toLocaleString("en-IN", opts(2))} %`;
  if (unit === "ratio" || unit === "index") return value.toLocaleString("en-IN", opts(2));
  const fallback = Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : 1;
  return value.toLocaleString("en-IN", opts(fallback)) + suffix(unit);
}

/** The decimals `format` uses by default, fixed for both values of a pair. */
function pairDigits(before: number, after: number, unit: string | null): number {
  if (unit === "share" || unit === "ratio" || unit === "index") return 2;
  if (unit === "count") return 0;
  const big = Math.max(Math.abs(before), Math.abs(after)) >= 100;
  return big || (Number.isInteger(before) && Number.isInteger(after)) ? 0 : 1;
}

/**
 * Baseline and scenario values with the same decimals, as many (up to four) as it takes to
 * show that they differ: "77.4 min → 77.4 min" next to a change of −0.006 min reads as a
 * mistake, and "4.94 % → 5 %" hides that 5 is rounded.
 */
export function formatPair(before: number, after: number, unit: string | null): [string, string] {
  if (before === after) return [format(before, unit), format(after, unit)];
  const start = pairDigits(before, after, unit);
  for (let digits = start; digits <= Math.max(start, 4); digits++) {
    const a = format(before, unit, digits);
    const b = format(after, unit, digits);
    if (a !== b) return [a, b];
  }
  return [format(before, unit, start), format(after, unit, start)];
}

/**
 * A signed change, with enough digits to show small changes: scenario effects are often a few
 * hundredths of a minute or of a percentage point, which plain rounding would show as 0.
 */
export function formatDelta(delta: number, unit: string | null): string {
  if (delta === 0) return "no change";
  const sign = delta > 0 ? "+" : "−";
  const size = Math.abs(unit === "share" ? delta * 100 : delta);
  const digits = size >= 100 ? 0 : Math.max(0, Math.min(4, 1 - Math.floor(Math.log10(size))));
  const text = size.toLocaleString("en-IN", { maximumFractionDigits: digits });
  return `${sign}${text}${unit === "share" ? " pp" : suffix(unit)}`;
}
