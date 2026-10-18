import { expect } from "vitest";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";
import "@testing-library/jest-dom/vitest";

// vitest-axe 0.1.0's own "extend-expect" entry point ships empty, so the matcher is registered directly.
expect.extend({ toHaveNoViolations });
