// Three pages (ADR 0024): the landing page at /, the Easy view at /easy and the full Pro screen
// at /pro. No router library: the path picks the page and links push history entries.

import { useSyncExternalStore } from "react";

export type Page = "landing" | "easy" | "pro";

export const PATH: Record<Page, string> = { landing: "/", easy: "/easy", pro: "/pro" };

export function pageOf(pathname: string): Page {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === PATH.easy) return "easy";
  if (path === PATH.pro) return "pro";
  return "landing";
}

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

/** Go to a page, keeping the city (?city=) and anything else asked for in `search`. */
export function navigate(page: Page, search: Record<string, string> = {}): void {
  const city = new URLSearchParams(window.location.search).get("city");
  const params = new URLSearchParams({ ...(city ? { city } : {}), ...search });
  const query = params.toString();
  window.history.pushState(null, "", `${PATH[page]}${query ? `?${query}` : ""}`);
  window.scrollTo(0, 0);
  notify();
}

export function usePage(): Page {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange);
      window.addEventListener("popstate", onChange);
      return () => {
        listeners.delete(onChange);
        window.removeEventListener("popstate", onChange);
      };
    },
    () => pageOf(window.location.pathname),
  );
}
