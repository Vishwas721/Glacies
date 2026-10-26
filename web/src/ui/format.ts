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

/**
 * Baseline and scenario values, with as many decimals (up to four) as it takes to show that
 * they differ: "77.4 min → 77.4 min" next to a change of −0.006 min reads as a mistake.
 */
export function formatPair(before: number, after: number, unit: string | null): [string, string] {
  const plain: [string, string] = [format(before, unit), format(after, unit)];
  if (before === after || plain[0] !== plain[1]) return plain;
  for (let digits = 1; digits <= 4; digits++) {
    const a = format(before, unit, digits);
    const b = format(after, unit, digits);
    if (a !== b) return [a, b];
  }
  return plain;
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
