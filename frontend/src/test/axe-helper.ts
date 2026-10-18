import { configureAxe } from "vitest-axe";

/** One shared axe instance for every accessibility test: rules kept to what applies to a component
 * rendered in isolation (landmarks/page-level rules would false-positive outside a full page). */
export const axe = configureAxe({
  rules: {
    region: { enabled: false },
    "landmark-one-main": { enabled: false },
    "page-has-heading-one": { enabled: false },
  },
});
