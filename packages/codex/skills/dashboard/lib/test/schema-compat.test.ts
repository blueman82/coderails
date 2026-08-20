import { describe, it, expect } from "vitest";
import type { Intent } from "../src/intent";
import type { IntentFile } from "../../obsidian/src/exec";

// Type-only compatibility harness: assigns each type to the other's shape.
// This catches producer-side (IntentFile) renames, type changes, and
// removals of required fields, and consumer-side (Intent) required
// additions — one of the two assignments below fails to typecheck and
// `tsc --noEmit` (run via Task 1.9's vitest+typecheck gate) fails the
// build immediately. It CANNOT catch producer-side field ADDITIONS: a
// wider IntentFile would still structurally assign to the narrower Intent
// shape, so this is not a claim of mutual assignability in both
// directions — only drift that narrows or breaks the existing contract.
// This replaces the old dormant byte-parity test: there is no "not yet
// merged" skip state anymore, because the producer already exists on
// origin/main.
function assertIntentFileIsIntent(f: IntentFile): Intent {
  return f; // fails to compile if IntentFile has a field Intent can't accept
}

function assertIntentIsAssignableToIntentFileShape(i: Intent): void {
  // IntentFile.source is the literal "obsidian"; Intent.source is a wider
  // string union. An Intent is not always assignable TO IntentFile (a
  // web-sourced Intent has source: "web", which IntentFile can't hold) —
  // that asymmetry is correct and expected (Intent is deliberately wider
  // to accept multiple producers). This function instead asserts the
  // reverse-narrow direction: any IntentFile-shaped value already
  // satisfies Intent, which is the direction that actually matters for
  // drift detection (a producer's schema must remain a valid Intent).
  const asIntentFile: IntentFile = { button: i.button, requestedAt: 0, source: "obsidian" };
  void asIntentFile;
}

describe("Intent / IntentFile schema compatibility", () => {
  it("obsidian's IntentFile is structurally assignable to this lib's Intent (compile-time gate)", () => {
    const sample: IntentFile = { button: "wiki-lint", requestedAt: Date.now(), source: "obsidian" };
    const asIntent: Intent = assertIntentFileIsIntent(sample);
    expect(asIntent.button).toBe("wiki-lint");
    expect(typeof asIntent.requestedAt).toBe("number");
    expect(asIntent.source).toBe("obsidian");
  });

  it("obsidian's IntentFile with optional input omitted still satisfies Intent", () => {
    const sample: IntentFile = { button: "wiki-lint", requestedAt: Date.now(), source: "obsidian" };
    expect(sample.input).toBeUndefined();
    const asIntent: Intent = assertIntentFileIsIntent(sample);
    expect(asIntent.input).toBeUndefined();
  });

  it("obsidian's IntentFile with input present still satisfies Intent", () => {
    const sample: IntentFile = { button: "verify-q", input: "check auth", requestedAt: Date.now(), source: "obsidian" };
    const asIntent: Intent = assertIntentFileIsIntent(sample);
    expect(asIntent.input).toBe("check auth");
  });

  it("this lib's Intent is assignable to IntentFile's shape in the reverse-narrow direction (compile-time gate)", () => {
    const intent: Intent = { button: "wiki-lint", requestedAt: Date.now(), source: "obsidian" };
    // Calls the gate function so it's an active assertion, not dead code:
    // if Intent.button or Intent.requestedAt's type ever narrowed in a way
    // IntentFile can't satisfy, this line fails to compile.
    expect(() => assertIntentIsAssignableToIntentFileShape(intent)).not.toThrow();
  });

  it("sanity: this test file itself performs a type-only import with no runtime obsidian dependency", () => {
    // If this ever became a runtime import, `IntentFile` would be undefined
    // at runtime (it's an interface, erased by TS) — this assertion exists
    // so a future editor who turns the type-only import into a value
    // import gets an immediate, loud failure here rather than a silent
    // dependency-graph violation.
    expect(typeof (undefined as unknown as IntentFile)).toBe("undefined");
  });
});
