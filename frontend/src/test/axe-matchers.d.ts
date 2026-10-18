import "vitest";
import type { AxeResults } from "axe-core";

// vitest-axe 0.1.0 ships no usable type augmentation for its matcher (its own d.ts re-exports the
// matcher as type-only, see test/setup.ts), so the `toHaveNoViolations()` assertion is declared here.
declare module "vitest" {
  interface Assertion<T = unknown> {
    toHaveNoViolations(): T extends AxeResults ? void : never;
  }
}
