// Client-side check against the same JSON Schema the engine generates
// (`glacies scenario schema`); the server still checks route and stop ids on save.

import Ajv2020, { type ErrorObject } from "ajv/dist/2020";

import schema from "../../../schemas/scenario.schema.json";
import type { Scenario } from "../api/types";

// strict: false lets Ajv ignore Pydantic's `discriminator` annotation.
const ajv = new Ajv2020({ allErrors: true, strict: false });
ajv.addSchema(schema, "scenario");
const whole = ajv.getSchema("scenario")!;
// Each mutation is checked against the definition its `type` names: checking the `oneOf`
// would also report every way it fails to be one of the other two kinds.
const DEFS: Record<string, string> = {
  remove_route: "RemoveRoute",
  modify_headway: "ModifyHeadway",
  add_route: "AddRoute",
};

const describe = (prefix: string, errors: ErrorObject[] | null | undefined) =>
  (errors ?? []).map((e) => `${prefix}${e.instancePath} ${e.message ?? "is invalid"}`.trim());

export function validateScenario(scenario: Scenario): string[] {
  const problems: string[] = [];
  if (!whole(scenario)) {
    problems.push(
      ...describe(
        "",
        whole.errors?.filter((e) => !/^\/mutations\/\d+/.test(e.instancePath)),
      ).map((p) => (p.startsWith(" ") ? `scenario${p}` : p)),
    );
  }
  scenario.mutations.forEach((m, i) => {
    const name = DEFS[(m as { type?: string }).type ?? ""];
    if (!name) {
      problems.push(`/mutations/${i} has an unknown type`);
      return;
    }
    const check = ajv.getSchema(`scenario#/$defs/${name}`)!;
    if (!check(m)) problems.push(...describe(`/mutations/${i}`, check.errors));
  });
  return problems;
}
