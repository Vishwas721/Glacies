import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing");

// The API is local: retry once, not three times, so errors show quickly.
const client = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
