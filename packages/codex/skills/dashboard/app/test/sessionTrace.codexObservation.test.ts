import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";

const digest = (value: string) => createHash("sha256").update(value).digest("hex");

describe("Codex transcript observations", () => {
  it("keeps invocation, verified read, failed read, and mention separate without storing text", async () => {
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
      "coderails.observation.kind": "read", "coderails.observation.target_kind": "skill",
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
