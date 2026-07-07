import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import { AssistantLinkPanel } from "../src/components/AssistantLinkPanel";
import type { DashboardSnapshot } from "../src/hooks/useDashboardState";
import type { QueueEntry } from "../src/lib/collect/queue";
import type { BuildEntry } from "../src/lib/collect/builds";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    trail: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    ...overrides,
  };
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

  describe("workflow-audit:propose-skill readable preview", () => {
    function proposalEntry(overrides: Partial<QueueEntry> = {}): QueueEntry {
      return pendingEntry({
        hash: "proposalHash",
        toolName: "workflow-audit:propose-skill",
        toolInput: {
          cluster_ngram: ["Bash:git log", "Bash:git push", "Skill:prime"],
          count: 3,
          sessions: ["s1", "s2", "s3"],
          task_summary: "Sessions repeatedly run git log, then git push, then invoke prime.",
          proposed_name: "git-log-push-prime",
          proposed_description: "Use when a session needs to review commits, push, and load context.",
        },
        ...overrides,
      });
    }

    it("renders proposed_name and proposed_description as visible text, not an opaque JSON dump", () => {
      const entry = proposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("git-log-push-prime");
      expect(html).toContain("Use when a session needs to review commits, push, and load context.");
      // Not rendered as a single opaque JSON.stringify blob.
      expect(html).not.toContain(JSON.stringify(entry.toolInput));
    });

    it("renders task_summary as visible text", () => {
      const entry = proposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("Sessions repeatedly run git log, then git push, then invoke prime.");
    });

    it("surfaces both the occurrence count and the session count, distinctly", () => {
      // count and sessions.length deliberately differ so a single "3"-style
      // assertion couldn't accidentally pass by conflating the two numbers.
      const entry = proposalEntry({
        toolInput: {
          cluster_ngram: ["Bash:git log", "Bash:git push", "Skill:prime"],
          count: 5,
          sessions: ["s1", "s2", "s3", "s4"],
          task_summary: "Sessions repeatedly run git log, then git push, then invoke prime.",
          proposed_name: "git-log-push-prime",
          proposed_description: "Use when a session needs to review commits, push, and load context.",
        },
      });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("5 occurrences");
      expect(html).toContain("4 sessions");
    });

    it("renders cluster_ngram as a joined chain", () => {
      const entry = proposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("Bash:git log");
      expect(html).toContain("Bash:git push");
      expect(html).toContain("Skill:prime");
    });

    it("still renders a non-workflow-audit toolName via the existing opaque preview path (negative control)", () => {
      const entry = pendingEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("#general");
      expect(html).not.toContain("git-log-push-prime");
    });

    it("falls back to the opaque preview when toolInput is malformed (missing proposed_name), without crashing", () => {
      const entry = proposalEntry({
        toolInput: {
          cluster_ngram: ["Bash:git log"],
          count: 1,
          sessions: ["s1"],
          task_summary: "malformed entry missing proposed_name",
          // proposed_name intentionally omitted
          proposed_description: "d",
        },
      });
      expect(() =>
        renderToStaticMarkup(
          createElement(
            DashboardContextTestProvider,
            { snapshot: emptySnapshot({ queue: [entry] }) },
            createElement(AssistantLinkPanel, { token: "t" })
          )
        )
      ).not.toThrow();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("malformed entry missing proposed_name");
    });

    it("falls back to the opaque preview when a field has the wrong type (cluster_ngram as a string, sessions as a string), without crashing", () => {
      const entry = proposalEntry({
        toolInput: {
          cluster_ngram: "Bash:git log", // wrong type: should be string[]
          count: 1,
          sessions: "s1", // wrong type: should be string[]
          task_summary: "malformed entry with wrong-typed array fields",
          proposed_name: "n",
          proposed_description: "d",
        },
      });
      expect(() =>
        renderToStaticMarkup(
          createElement(
            DashboardContextTestProvider,
            { snapshot: emptySnapshot({ queue: [entry] }) },
            createElement(AssistantLinkPanel, { token: "t" })
          )
        )
      ).not.toThrow();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("malformed entry with wrong-typed array fields");
    });

    it("still renders Approve/Deny buttons for a workflow-audit:propose-skill entry, untouched", () => {
      const entry = proposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("Approve");
      expect(html).toContain("Deny");
    });
  });

  describe("approve-builder build-state visibility", () => {
    function approvedProposalEntry(overrides: Partial<QueueEntry> = {}): QueueEntry {
      return pendingEntry({
        hash: "buildHash1",
        toolName: "workflow-audit:propose-skill",
        status: "approved",
        toolInput: {
          cluster_ngram: ["Bash:git log", "Bash:git push"],
          count: 3,
          sessions: ["s1", "s2", "s3"],
          task_summary: "Sessions repeatedly run git log then git push.",
          proposed_name: "git-log-push",
          proposed_description: "Use when a session reviews commits then pushes.",
        },
        ...overrides,
      });
    }

    function buildEntry(overrides: Partial<BuildEntry> = {}): BuildEntry {
      return { schemaVersion: 1, hash: "buildHash1", state: "running", ...overrides };
    }

    it("renders nothing build-related for an approved entry with no build entry yet (control)", () => {
      const entry = approvedProposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).not.toContain("building");
      expect(html).not.toContain("awaiting your merge");
      expect(html).not.toContain("failed:");
      expect(html).not.toContain("builder dead");
    });

    it('renders "building" for state running with a fresh heartbeat', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "running", heartbeatAgeMs: 5_000 });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("building");
      expect(html).not.toContain("builder dead");
    });

    it('renders "builder dead" for state running with a stale heartbeat (> 3 minutes)', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "running", heartbeatAgeMs: 4 * 60 * 1000 });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("builder dead");
    });

    it('renders "PR open — awaiting your merge" with a link to prUrl for state pr_open', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/999",
      });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("awaiting your merge");
      expect(html).toContain("https://github.com/blueman82/coderails/pull/999");
    });

    it('renders "failed: <reason> — delete builds/<hash> to retry" for state failed', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "failed", failureReason: "hash_mismatch:abc123" });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("failed: hash_mismatch:abc123");
      expect(html).toContain(`delete builds/${build.hash} to retry`);
    });

    it("does not render a build-state row for an unrelated approved entry (wrong toolName), even if a build entry with a matching hash exists", () => {
      const entry = pendingEntry({ hash: "buildHash1", status: "approved" });
      const build = buildEntry({ state: "pr_open", prUrl: "https://example.com/pr/1" });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).not.toContain("awaiting your merge");
    });
  });
});
