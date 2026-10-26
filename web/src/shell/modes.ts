// The four working modes of the screen. Each decides what the side panel and the inspector
// show; the map, the scenario being edited and the chosen result are shared by all of them.

export type Mode = "explore" | "design" | "compare" | "data";

export const MODES: { id: Mode; label: string; title: string; summary: string }[] = [
  {
    id: "explore",
    label: "Explore",
    title: "Explore the network",
    summary:
      "The baseline timetable, where people live, where the proxy puts jobs, and what each zone reaches.",
  },
  {
    id: "design",
    label: "Design",
    title: "Design a scenario",
    summary: "Take routes out, change how often they run, or draw a new one; save and simulate.",
  },
  {
    id: "compare",
    label: "Compare",
    title: "Compare with the baseline",
    summary: "A finished run against today: what moved, where, and for whom.",
  },
  {
    id: "data",
    label: "Data",
    title: "Data and provenance",
    summary: "Where every input comes from, its licence, and what the four labels mean.",
  },
];

const KEY = "mode";

/** The mode in the address bar (?mode=), so a reload or a shared link opens the same view. */
export function initialMode(): Mode {
  const asked = new URLSearchParams(window.location.search).get(KEY);
  return MODES.some((m) => m.id === asked) ? (asked as Mode) : "explore";
}

export function rememberMode(mode: Mode) {
  const url = new URL(window.location.href);
  url.searchParams.set(KEY, mode);
  window.history.replaceState(null, "", url);
}
