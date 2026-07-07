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

  // Negative control for the premise change: the OLD (pre-merge) plan
  // treated requestedAt as an ISO 8601 string. The merged producer writes
  // a number (Date.now()). An ISO string must now be REJECTED.
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
});
