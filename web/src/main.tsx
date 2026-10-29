import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/archivo/wdth.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import { Root } from "./Root";
import { initTheme } from "./ui/theme";
import "./index.css";
import "./shell/shell.css";
import "./map/hud.css";
import "./inspect/inspect.css";
import "./compare/compare.css";
import "./runs/runs.css";
import "./scenario/builder.css";
import "./ui/chrome.css";
import "./landing/landing.css";
import "./easy/easy.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

// Before the first paint, so a light-theme viewer never sees a dark flash.
initTheme();

// The API is local: retry once, not three times, so errors show quickly.
const client = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>
  </StrictMode>,
);
