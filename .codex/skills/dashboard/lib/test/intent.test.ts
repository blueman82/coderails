import { describe, it, expect } from "vitest";
import { parseIntent, IntentValidationError } from "../src/intent";

describe("parseIntent", () => {
  it("accepts a well-formed intent with all required fields (epoch-ms requestedAt)", () => {
    const intent = parseIntent({
      button: "wiki-lint",
      requestedAt: 1751835600000,
      source: "web",
    });
    expect(intent).toEqual({
      button: "wiki-lint",
      requestedAt: 1751835600000,
      source: "web",
    });
  });

  it("accepts an optional input field", () => {
    const intent = parseIntent({
      button: "verify-q",
      input: "check the auth flow",
      requestedAt: 1751835600000,
      source: "obsidian",
    });
    expect(intent.input).toBe("check the auth flow");
  });

  // Fixture matching EXACTLY what the merged obsidian/src/exec.ts producer
  // writes to <dashboard-dir>/queue/<runId>.json (see IntentFile there).
  it("accepts the exact shape the merged obsidian producer writes", () => {
    const intent = parseIntent({
      button: "wiki-lint",
      requestedAt: Date.now(),
      source: "obsidian",
    });
    expect(intent.source).toBe("obsidian");
    expect(typeof intent.requestedAt).toBe("number");
  });

  it("accepts any string as source, not just the three named literals", () => {
    const intent = parseIntent({
      button: "wiki-lint",
      requestedAt: 1751835600000,
      source: "routine-sweeper",
    });
    expect(intent.source).toBe("routine-sweeper");
  });

  it("throws IntentValidationError when button is missing", () => {
    expect(() =>
      parseIntent({ requestedAt: 1751835600000, source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when button is not a string", () => {
    expect(() =>
      parseIntent({ button: 42, requestedAt: 1751835600000, source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when requestedAt is missing", () => {
    expect(() => parseIntent({ button: "wiki-lint", source: "web" })).toThrow(
      IntentValidationError
    );
  });

  // Negative control: requestedAt is an epoch-ms number (Date.now()), not an
  // ISO 8601 string. An ISO string must be REJECTED.
  it("throws IntentValidationError when requestedAt is an ISO 8601 string instead of epoch-ms number", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: "2026-07-06T20:00:00.000Z", source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when requestedAt is not a finite number", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: Number.NaN, source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when source is missing", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: 1751835600000 })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when source is not a string", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: 7 })
    ).toThrow(IntentValidationError);
  });

  // Negative control: button must be a string; a wrong-type button (the
  // shape a hostile or buggy producer might write) must be rejected.
  it("throws IntentValidationError when button is an object instead of a string", () => {
    expect(() =>
      parseIntent({ button: { name: "wiki-lint" }, requestedAt: 1751835600000, source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when input is present but not a string", () => {
    expect(() =>
      parseIntent({
        button: "wiki-lint",
        input: 123,
        requestedAt: 1751835600000,
        source: "web",
      })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError for a non-object payload", () => {
    expect(() => parseIntent("not an object")).toThrow(IntentValidationError);
    expect(() => parseIntent(null)).toThrow(IntentValidationError);
    expect(() => parseIntent(undefined)).toThrow(IntentValidationError);
  });

  // Behaviour-pinning: requestedAt is only checked for type + finiteness, not
  // range or sign. These pin the CURRENT design so a future change is a
  // deliberate diff, not an accidental one.
  it("accepts requestedAt of 0 (pins current design: no lower-bound check)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 0, source: "web" });
    expect(intent.requestedAt).toBe(0);
  });

  it("accepts a negative requestedAt (pins current design: sign is not validated)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: -1751835600000, source: "web" });
    expect(intent.requestedAt).toBe(-1751835600000);
  });

  it("throws IntentValidationError when requestedAt is Infinity", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: Number.POSITIVE_INFINITY, source: "web" })
    ).toThrow(IntentValidationError);
  });

  it("throws IntentValidationError when requestedAt is -Infinity", () => {
    expect(() =>
      parseIntent({ button: "wiki-lint", requestedAt: Number.NEGATIVE_INFINITY, source: "web" })
    ).toThrow(IntentValidationError);
  });

  // Behaviour-pinning: parseIntent only checks button/source are strings, not
  // that they're non-empty or a known name. The runner is responsible for
  // rejecting unknown button names at lookup time — this is not that check.
  it("accepts an empty-string button (pins current design: runner rejects unknown names at lookup)", () => {
    const intent = parseIntent({ button: "", requestedAt: 1751835600000, source: "web" });
    expect(intent.button).toBe("");
  });

  it("accepts an empty-string source (pins current design: no non-empty check)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: "" });
    expect(intent.source).toBe("");
  });

  it("accepts an empty-string input (pins current design)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: "web", input: "" });
    expect(intent.input).toBe("");
  });

  it("accepts a whitespace-only input (pins current design)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: "web", input: "   " });
    expect(intent.input).toBe("   ");
  });

  // Behaviour-pinning: parseIntent does not reject leading-dash-looking input.
  // Flag-smuggling enforcement deliberately lives in buildArgv (the '--'
  // sentinel + producer-side leading-dash rejection there) — parseIntent is
  // a schema/type gate, not that enforcement point.
  it("accepts input that looks like a CLI flag (pins current design: buildArgv, not parseIntent, enforces flag-smuggling)", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: "web", input: "-rf" });
    expect(intent.input).toBe("-rf");
  });

  // Behaviour-pinning: unknown extra fields are silently dropped, not
  // rejected. The returned object has exactly the four known keys.
  it("silently drops unknown extra fields (pins current design)", () => {
    const intent = parseIntent({
      button: "wiki-lint",
      requestedAt: 1751835600000,
      source: "web",
      retryCount: 3,
    });
    expect(Object.keys(intent).sort()).toEqual(["button", "requestedAt", "source"].sort());
  });
});
