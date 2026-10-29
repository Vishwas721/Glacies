// Pieces every page shares: the wordmark (home), links between pages and the theme switch.

import type { MouseEvent, ReactNode } from "react";

import { navigate, type Page, PATH } from "../router";
import { setTheme, useTheme } from "./theme";

/** A link to another page that moves without reloading (and still opens in a new tab). */
export function PageLink(props: {
  to: Page;
  search?: Record<string, string>;
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
}) {
  const { to, search, className, children } = props;
  const query = new URLSearchParams(search).toString();
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(to, search);
  };
  return (
    <a
      href={`${PATH[to]}${query ? `?${query}` : ""}`}
      className={className}
      aria-label={props["aria-label"]}
      onClick={onClick}
    >
      {children}
    </a>
  );
}

/** The Glacies mark: two facets of an ice crystal, the outer one in the accent. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg className="glyph" viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <polygon points="16,2 29,9.5 29,22.5 16,30 3,22.5 3,9.5" />
      <polygon points="16,9 22,12.5 22,19.5 16,23 10,19.5 10,12.5" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <PageLink to="landing" className="wordmark" aria-label="Glacies, home">
      <Mark />
      <span>Glacies</span>
    </PageLink>
  );
}

export function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
      onClick={() => setTheme(next)}
    >
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {theme === "dark" ? (
          // A sun: the theme the button switches to.
          <>
            <circle cx="10" cy="10" r="3.6" />
            <path d="M10 1.8v2.4M10 15.8v2.4M1.8 10h2.4M15.8 10h2.4M4.2 4.2l1.7 1.7M14.1 14.1l1.7 1.7M4.2 15.8l1.7-1.7M14.1 5.9l1.7-1.7" />
          </>
        ) : (
          <path d="M15.5 12.6A6.5 6.5 0 0 1 7.4 4.5a6.5 6.5 0 1 0 8.1 8.1z" />
        )}
      </svg>
    </button>
  );
}
