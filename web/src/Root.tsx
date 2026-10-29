// The page for the address: landing at /, the Easy view at /easy, the full screen at /pro.

import { App } from "./App";
import { Easy } from "./easy/Easy";
import { Landing } from "./landing/Landing";
import { usePage } from "./router";

export function Root() {
  const page = usePage();
  if (page === "easy") return <Easy />;
  if (page === "pro") return <App />;
  return <Landing />;
}
