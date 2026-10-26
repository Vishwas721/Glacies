// Screen-width breakpoints shared by the layout (shell.css) and the code that adapts to them.

import { useSyncExternalStore } from "react";

/** The inspector stops being a column and opens over the map. */
export const NARROW = "(max-width: 1280px)";
/** The mode panel also opens over the map. */
export const TABLET = "(max-width: 900px)";
/** A phone: the rail is a tab bar and panels are bottom sheets; no scenario building. */
export const PHONE = "(max-width: 700px)";

export const matches = (query: string): boolean =>
  typeof window.matchMedia === "function" && window.matchMedia(query).matches;

export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => matches(query),
  );
}
