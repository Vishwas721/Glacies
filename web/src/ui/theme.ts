// Light or dark (ADR 0024): the viewer's choice, else their system's. Stored per browser; the
// attribute on <html> switches the CSS tokens and the map picks its basemap from it.

import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "glacies.theme";
const listeners = new Set<() => void>();

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked: fall back to the system
  }
}

function system(): Theme {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export const currentTheme = (): Theme =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

/** Set the theme on <html> from storage or the system; run once before the first render. */
export function initTheme(): void {
  document.documentElement.dataset.theme = stored() ?? system();
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // not remembered, still applied
  }
  listeners.forEach((l) => l());
}

export function useTheme(): Theme {
  return useSyncExternalStore((onChange) => {
    listeners.add(onChange);
    return () => listeners.delete(onChange);
  }, currentTheme);
}
