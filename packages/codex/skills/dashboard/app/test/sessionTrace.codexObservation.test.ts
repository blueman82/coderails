import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";
import { observeCodexSource } from "../src/lib/collect/codexTraceObservation";
import type { NativeSource } from "../src/lib/collect/codexTraceNative";

const digest = (value: string) => createHash("sha256").update(value).digest("hex");

describe("Codex transcript observations", () => {
  it.each(["See /repo/notAGENTS.md.", "See ./CLAUDE.mdx.", "See AGENTS.md.backup", "See CLAUDE.md.template"])("rejects a partial filename in %s", async (body) => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows, { type: "response_item", payload: { type: "message", role: "assistant",
      content: [{ type: "output_text", text: body }] } }]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    expect(page.events.some((event) => event.attributes["coderails.observation.kind"] === "mention")).toBe(false);
  });

  it("bounds synchronous scanning of unmatched slash-separated paths", async () => {
    const { deps } = await fixture();
    const page = await readCodexTracePage("parent", null, 30, deps);
    const event = { ...page.events[0], attributes: {},
      provenance: { ...page.events[0].provenance, sourceOrdinal: 1 } };
    const source: NativeSource = { path: "fixture.jsonl", id: event.provenance.sourceId,
      text: "", fingerprint: "fixture", cursor: "1", errors: [], ordinals: [1], rows: [
        { type: "response_item", payload: { type: "message", content: [
          { type: "output_text", text: `See /${"segment/".repeat(26)}notes.txt.` },
        ] } },
      ] };
    const started = performance.now();
    observeCodexSource(source, [event]);
    expect(performance.now() - started).toBeLessThan(1000);
    expect(event.attributes).not.toHaveProperty("coderails.observation.kind");
  });

  it.each(["See /repo/AGENTS.md.", "See ./CLAUDE.md."])("retains a full filename in %s", async (body) => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows, { type: "response_item", payload: { type: "message", role: "assistant",
      content: [{ type: "output_text", text: body }] } }]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    expect(page.events.some((event) => event.attributes["coderails.observation.kind"] === "mention")).toBe(true);
  });

  it("does not establish installation from an arbitrary skill path", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows,
      { type: "response_item", payload: { type: "function_call", name: "read_file", call_id: "scratch",
        arguments: JSON.stringify({ path: "/scratch/uninstalled/skills/wiki-query/SKILL.md" }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "scratch", is_error: false,
        output: "complete 😀" } },
    ]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    expect(page.events.find((event) => event.name === "function_call_output" &&
      event.attributes["coderails.native.call_id"] === "scratch")?.attributes)
      .toMatchObject({ "coderails.observation.kind": "uncertain", "coderails.observation.bytes": 13 });
  });

  it("recognizes the declared Read file_path input", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows,
      { type: "response_item", payload: { type: "function_call", name: "Read", call_id: "read",
        arguments: JSON.stringify({ file_path: "/repo/AGENTS.md" }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "read", is_error: false,
        output: "known context" } },
    ]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    expect(page.events.find((event) => event.name === "function_call_output" &&
      event.attributes["coderails.native.call_id"] === "read")?.attributes["coderails.observation.kind"])
      .toBe("read");
  });

  it("keeps invocation, unproved skill-file read, failed read and mention separate without text", async () => {
    const { deps, parent, rows, save } = await fixture();
    const skill = "/plugin/skills/agentic-loop/SKILL.md";
    const secret = "PRIVATE_OBSERVATION_CANARY_π";
    await save(parent, [...rows,
      { type: "response_item", payload: { type: "function_call", name: "skill", call_id: "invoke",
        arguments: JSON.stringify({ name: "agentic-loop", private: secret }) } },
      { type: "response_item", payload: { type: "function_call", name: "read_file", call_id: "read",
        arguments: JSON.stringify({ path: skill }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "read", is_error: false,
        output: secret } },
      { type: "response_item", payload: { type: "function_call", name: "read_file", call_id: "failed",
        arguments: JSON.stringify({ path: skill }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "failed", is_error: true,
        output: secret } },
      { type: "response_item", payload: { type: "message", role: "assistant",
        content: [{ type: "output_text", text: `See ${skill}. ${secret}` }] } },
    ]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    const byCall = (id: string, name: string) => page.events.find((event) =>
      event.name === name && event.attributes["coderails.native.call_id"] === id);
    expect(byCall("invoke", "function_call")?.attributes).toMatchObject({
      "coderails.observation.kind": "invocation", "coderails.observation.target_kind": "skill",
      "coderails.observation.target_sha256": digest("skill:agentic-loop"),
    });
    expect(byCall("read", "function_call_output")?.attributes).toMatchObject({
      "coderails.observation.kind": "uncertain", "coderails.observation.target_kind": "skill",
      "coderails.observation.target_sha256": digest("skill:agentic-loop"),
      "coderails.observation.bytes": Buffer.byteLength(secret, "utf8"),
    });
    expect(byCall("failed", "function_call_output")?.attributes["coderails.observation.kind"]).toBe("failed_read");
    expect(page.events.find((event) => event.attributes["coderails.observation.kind"] === "mention")?.attributes)
      .toMatchObject({ "coderails.observation.target_sha256": digest("skill:agentic-loop") });
    expect(JSON.stringify(page)).not.toContain(secret);
  });

  it("ignores unrelated reads and joins the same context target across paths", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows,
      { type: "response_item", payload: { type: "function_call", name: "Read", call_id: "other",
        arguments: JSON.stringify({ path: "/private/secrets.txt" }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "other", is_error: false,
        output: "secret" } },
      { type: "response_item", payload: { type: "function_call", name: "Read", call_id: "context",
        arguments: JSON.stringify({ path: "/repo/AGENTS.md" }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "context", is_error: false,
        output: "known context" } },
    ]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    const byCall = (id: string) => page.events.find((event) =>
      event.name === "function_call_output" && event.attributes["coderails.native.call_id"] === id);
    expect(byCall("other")?.attributes["coderails.observation.kind"]).toBeUndefined();
    expect(byCall("context")?.attributes).toMatchObject({
      "coderails.observation.kind": "read", "coderails.observation.target_kind": "context",
      "coderails.observation.target_sha256": digest("context:AGENTS.md"),
    });
  });

  it("marks duplicate or unproved read results uncertain and keeps worker joins", async () => {
    const { deps, child, children, save } = await fixture();
    const read = { type: "response_item", payload: { type: "function_call", name: "read_file", call_id: "same",
      arguments: JSON.stringify({ path: "/context/AGENTS.md" }) } };
    await save(child, [...children, read, read,
      { type: "response_item", payload: { type: "function_call_output", call_id: "same", output: "private" } },
      { type: "response_item", payload: { type: "function_call", name: "read_file", call_id: "unproved",
        arguments: JSON.stringify({ path: "/context/AGENTS.md" }) } },
      { type: "response_item", payload: { type: "function_call_output", call_id: "unproved", output: "private" } },
    ]);
    const page = await readCodexTracePage("parent", null, 40, deps);
    const observed = page.events.filter((event) => event.attributes["coderails.observation.kind"] !== undefined);
    expect(observed.every((event) => event.attributes["coderails.observation.kind"] === "uncertain")).toBe(true);
    expect(observed.every((event) => event.parentSpanId !== null &&
      event.attributes["coderails.actor.id"] === "child-one")).toBe(true);
    expect(JSON.stringify(page)).not.toContain("private");
  });

  it("keeps cumulative cache usage marked as cumulative", async () => {
    const { deps, parent, rows, save } = await fixture();
    await save(parent, [...rows, { type: "event_msg", payload: { type: "token_count", info: {
      total_token_usage: { input_tokens: 20, output_tokens: 3, cached_input_tokens: 12 } } } }]);
    const page = await readCodexTracePage("parent", null, 20, deps);
    const counts = page.events.filter((event) => event.name === "token_count");
    expect(counts.at(-1)?.attributes).toMatchObject({
      "gen_ai.usage.cache_read_input_tokens": 12,
      "coderails.usage.semantics": "cumulative",
    });
  });
});
