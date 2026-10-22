// Number formatting for labelled quantities; the unit names are the API's `fields` units.

export function format(value: number, unit: string | null): string {
  if (unit === "share")
    return `${(value * 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })} %`;
  if (unit === "ratio") return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  const digits = Math.abs(value) >= 100 || Number.isInteger(value) ? 0 : 1;
  const text = value.toLocaleString("en-IN", { maximumFractionDigits: digits });
  return unit && !["count", "share", "ratio"].includes(unit) ? `${text} ${unit}` : text;
}
