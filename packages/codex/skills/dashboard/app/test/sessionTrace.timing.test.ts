import { describe, expect, it } from "vitest";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";
import { fixture } from "./sessionTraceFixture";

describe("Codex native session trace", () => {
  it("derives a request/result timestamp gap with two native refs while retaining emitted duration", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [rows[0],
      { timestamp: "2026-09-28T12:00:01Z", type: "response_item", payload: { type: "function_call", name: "exec_command", call_id: "timed-call" } },
      { timestamp: "2026-09-28T12:00:02Z", type: "response_item", payload: { type: "function_call_output", call_id: "timed-call", duration_ms: 42 } },
      ...rows.slice(1)]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    const request = page.events.find((event) => event.attributes["coderails.native.call_id"] === "timed-call" && event.name === "function_call");
    const result = page.events.find((event) => event.attributes["coderails.native.call_id"] === "timed-call" && event.name === "function_call_output");
    expect(request?.attributes).toMatchObject({
      "coderails.elapsed_gap_ms": 1000,
      "coderails.elapsed_gap.basis": "derived",
      "coderails.elapsed_gap.method": "timestamp_difference",
      "coderails.elapsed_gap.cause": "unknown",
      "coderails.elapsed_gap.start_source_ref": request?.provenance.sourceRef.recordId,
      "coderails.elapsed_gap.end_source_ref": result?.provenance.sourceRef.recordId,
    });
    expect(result?.attributes).toMatchObject({ "coderails.duration_ms": 42, "coderails.duration.basis": "source" });
    expect(request?.attributes).toMatchObject({ "coderails.duration_ms": null, "coderails.duration.basis": "unavailable" });
    expect(request?.attributes["coderails.start_time.basis"]).toBe("source");
    expect(request?.attributes["coderails.end_time.basis"]).toBe("unavailable");
    expect(request?.startTimeUnixNano).not.toBeNull();
    expect(request?.endTimeUnixNano).toBeNull();
  });

  it("leaves gaps unavailable for missing, invalid, reversed, or ambiguous timing", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [rows[0],
      { type: "response_item", payload: { type: "function_call", call_id: "missing" } },
      { timestamp: "2026-09-28T12:00:02Z", type: "response_item", payload: { type: "function_call_output", call_id: "missing" } },
      { timestamp: "bad", type: "response_item", payload: { type: "function_call", call_id: "invalid" } },
      { timestamp: "2026-09-28T12:00:02Z", type: "response_item", payload: { type: "function_call_output", call_id: "invalid" } },
      { timestamp: "2026-09-28T12:00:03Z", type: "response_item", payload: { type: "function_call", call_id: "reverse" } },
      { timestamp: "2026-09-28T12:00:02Z", type: "response_item", payload: { type: "function_call_output", call_id: "reverse" } },
      { timestamp: "2026-09-28T12:00:01Z", type: "response_item", payload: { type: "function_call", call_id: "ambiguous" } },
      { timestamp: "2026-09-28T12:00:02Z", type: "response_item", payload: { type: "function_call_output", call_id: "ambiguous" } },
      { timestamp: "2026-09-28T12:00:03Z", type: "response_item", payload: { type: "function_call_output", call_id: "ambiguous" } },
      ...rows.slice(1)]);
    const page = await readCodexTracePage("parent", null, 40, deps);
    for (const callId of ["missing", "invalid", "reverse", "ambiguous"]) {
      expect(page.events.find((event) => event.name === "function_call" && event.attributes["coderails.native.call_id"] === callId)?.attributes["coderails.elapsed_gap_ms"]).toBeUndefined();
    }
    for (const callId of ["missing", "invalid"]) {
      const request = page.events.find((event) => event.name === "function_call" && event.attributes["coderails.native.call_id"] === callId);
      expect(request?.startTimeUnixNano).toBeNull();
      expect(request?.attributes).toMatchObject({ "coderails.start_time.basis": "unavailable",
        "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
        "coderails.duration.basis": "unavailable" });
    }
  });

});
