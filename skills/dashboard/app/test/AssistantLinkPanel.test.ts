import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import { AssistantLinkPanel } from "../src/components/AssistantLinkPanel";
import type { DashboardSnapshot } from "../src/hooks/useDashboardState";
import type { QueueEntry } from "../src/lib/collect/queue";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return { sessions: [], loops: [], gates: [], trail: [], health: [], runs: [], queue: [], ...overrides };
}

function pendingEntry(overrides: Partial<QueueEntry> = {}): QueueEntry {
  return {
    hash: "abc123",
    toolName: "mcp__claude_ai_Slack__slack_send_message",
    toolInput: { channel: "#general", text: "hello team" },
    createdAt: Date.now(),
    status: "pending",
    ...overrides,
  };
}

describe("AssistantLinkPanel", () => {
  it("renders an empty state when there are no pending entries", () => {
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot() },
        createElement(AssistantLinkPanel, { token: "t" })
      )
    );
    expect(html).toContain("no pending approvals");
  });

  it("renders toolName, Approve/Deny buttons, and an opaque JSON preview of toolInput for a pending entry", () => {
    const entry = pendingEntry();
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ queue: [entry] }) },
        createElement(AssistantLinkPanel, { token: "t" })
      )
    );
    expect(html).toContain(entry.toolName);
    expect(html).toContain("Approve");
    expect(html).toContain("Deny");
    // Opaque rendering: the raw JSON.stringify of toolInput appears verbatim (HTML-escaped by
    // React), never a destructured field like entry.toolInput.text rendered standalone.
    expect(html).toContain("#general");
  });

  it("does not render approved/denied entries in the pending list (only status 'pending' entries)", () => {
    const approved = pendingEntry({ hash: "approvedHash", status: "approved" });
    const denied = pendingEntry({ hash: "deniedHash", status: "denied" });
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ queue: [approved, denied] }) },
        createElement(AssistantLinkPanel, { token: "t" })
      )
    );
    expect(html).toContain("no pending approvals");
  });

  it("does not render any of the three explicitly-deferred panel slots (tasks, email-checked, routine-runs)", () => {
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ queue: [pendingEntry()] }) },
        createElement(AssistantLinkPanel, { token: "t" })
      )
    );
    expect(html.toLowerCase()).not.toContain("routine");
    expect(html.toLowerCase()).not.toContain("email");
    expect(html.toLowerCase()).not.toContain("tasks due");
  });
});
