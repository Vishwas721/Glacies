// Number formatting for labelled quantities; the unit names are the API's `fields` units.

const SUFFIX: Record<string, string> = { minutes: "min", index: "" };

function suffix(unit: string | null): string {
  if (!unit || ["count", "share", "ratio"].includes(unit)) return "";
  const s = SUFFIX[unit] ?? unit;
  return s ? ` ${s}` : "";
}

export function format(value: number, unit: string | null): string {
  if (unit === "share")
    return `${(value * 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })} %`;
  if (unit === "ratio" || unit === "index")
    return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const digits = Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : 1;
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits }) + suffix(unit);
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
