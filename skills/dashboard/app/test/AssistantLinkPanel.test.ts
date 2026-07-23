import { describe, it, expect, afterEach, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import {
  AssistantLinkPanel,
  isHeartbeatStale,
  postDecision,
  renderDecisionFeedback,
  renderBuildStatus,
  formatElapsed,
} from "../src/components/AssistantLinkPanel";
import type { DashboardSnapshot } from "../src/hooks/useDashboardState";
import type { QueueEntry } from "../src/lib/collect/queue";
import type { BuildEntry } from "../src/lib/collect/builds";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    contextTrend: null,
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

    it("renders an explicit 'approved — no build claimed' state for an approved entry with no build entry yet (L2-WU7 DEFECT B: previously rendered nothing at all)", () => {
      const entry = approvedProposalEntry();
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("approved");
      expect(html).toContain("no build claimed");
      expect(html).not.toContain("building");
      expect(html).not.toContain("awaiting your merge");
      expect(html).not.toContain("failed:");
      expect(html).not.toContain("builder dead");
    });

    it("does not render the 'no build claimed' state for a denied entry (negative control: only approved workflow-audit:propose-skill entries with no build get this treatment)", () => {
      const entry = pendingEntry({
        hash: "deniedNoBuildHash",
        toolName: "workflow-audit:propose-skill",
        status: "denied",
      });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).not.toContain("no build claimed");
    });

    it("renders the current phase label for a running build that reported one", () => {
      const build = buildEntry({ state: "running", phase: "pushing", startedAt: 1000, heartbeatAt: 1000 });
      const html = renderToStaticMarkup(renderBuildStatus(build, 1000, new Set()));
      expect(html).toContain("pushing");
    });

    it("falls back to plain 'building' for a running build with no phase reported yet", () => {
      const build = buildEntry({ state: "running", startedAt: 1000, heartbeatAt: 1000 });
      const html = renderToStaticMarkup(renderBuildStatus(build, 1000, new Set()));
      expect(html).toContain("building");
      // no stray phase word leaks in
      expect(html).not.toContain("authoring");
      expect(html).not.toContain("opening_pr");
    });

    it("renders an elapsed time for a running build from startedAt against now", () => {
      const startedAt = 1_000_000;
      const now = startedAt + 6 * 60_000 + 12_000; // 6m12s later
      const build = buildEntry({ state: "running", startedAt, heartbeatAt: now });
      const html = renderToStaticMarkup(renderBuildStatus(build, now, new Set()));
      expect(html).toContain("6m");
    });

    it("formatElapsed renders m/s from a millisecond delta and returns empty for unknown inputs", () => {
      expect(formatElapsed(1000, 1000 + 6 * 60_000 + 12_000)).toBe("6m12s");
      expect(formatElapsed(1000, 1000 + 45_000)).toBe("45s");
      expect(formatElapsed(undefined, 1000)).toBe("");
      expect(formatElapsed(1000, null)).toBe("");
    });

    it("after-merge: a pr_open build whose PR left the open set renders 'resolved', not 'awaiting your merge'", () => {
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/104",
      });
      // PR 104 is NOT in the open-PR set → it was merged or closed
      const html = renderToStaticMarkup(renderBuildStatus(build, Date.now(), new Set([200, 201])));
      expect(html).toContain("resolved");
      expect(html).not.toContain("awaiting your merge");
    });

    it("after-merge: a pr_open build whose PR is still open renders 'awaiting your merge' (negative control)", () => {
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/104",
      });
      const html = renderToStaticMarkup(renderBuildStatus(build, Date.now(), new Set([104])));
      expect(html).toContain("awaiting your merge");
      expect(html).not.toContain("resolved");
    });

    it("after-merge: an untrusted (null) open-PR set never renders 'resolved' — gates unloaded/failed/degraded", () => {
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/104",
      });
      // null = gates not yet loaded, or a repo degraded to an error entry.
      // An open PR absent from an empty set must NOT be misread as resolved.
      const html = renderToStaticMarkup(renderBuildStatus(build, Date.now(), null));
      expect(html).toContain("awaiting your merge");
      expect(html).not.toContain("resolved");
    });

    it("after-merge: a malformed prUrl on a pr_open build never renders 'resolved' (unparseable PR number is not a join miss)", () => {
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/",
      });
      // prNumberFromUrl returns undefined → the build doesn't participate in
      // the join → it falls back to "awaiting your merge", not "resolved".
      const html = renderToStaticMarkup(renderBuildStatus(build, Date.now(), new Set([200])));
      expect(html).toContain("awaiting your merge");
      expect(html).not.toContain("resolved");
    });

    it('renders "building" for state running (SSR: no build entry heartbeat data needed)', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "running", heartbeatAt: Date.now() });
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

    it('renders "building" for state running with no heartbeatAt yet (heartbeat file not written this instant — a real transient just after the running state.json lands)', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "running", heartbeatAt: undefined });
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

    // renderToStaticMarkup never runs the component's mount effect, so its
    // internal "now" stays null and isHeartbeatStale (below) always reports
    // false through the full component in this test harness — asserted
    // directly here as the SSR-safe "never stale before mount" contract.
    // The live client behavior (staleness advancing against the panel's own
    // ticking clock, independent of the last fs.watch-triggered collect) is
    // covered by the isHeartbeatStale unit tests further down.
    it('never renders "builder dead" via SSR, even with a very stale heartbeat, because now is null before mount', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "running", heartbeatAt: Date.now() - 4 * 60 * 1000 });
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

    it('renders "PR open — awaiting your merge" with a link to prUrl for state pr_open', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({
        state: "pr_open",
        prUrl: "https://github.com/blueman82/coderails/pull/999",
      });
      // PR 999 present in the open-PR set (gates) so the after-merge join
      // reads it as still open → "awaiting your merge".
      const openGate = { repo: "blueman82/coderails", number: 999, title: "t", headSha: "", review: {}, evals: {}, state: "merge-ready" };
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build], gates: [openGate as never] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("awaiting your merge");
      expect(html).toContain("https://github.com/blueman82/coderails/pull/999");
    });

    it('falls back to plain-text "PR open" (no link) when prUrl is a non-https scheme, e.g. javascript:', () => {
      const entry = approvedProposalEntry();
      const build = buildEntry({ state: "pr_open", prUrl: "javascript:alert(1)" });
      const html = renderToStaticMarkup(
        createElement(
          DashboardContextTestProvider,
          { snapshot: emptySnapshot({ queue: [entry], builds: [build] }) },
          createElement(AssistantLinkPanel, { token: "t" })
        )
      );
      expect(html).toContain("awaiting your merge");
      expect(html).not.toContain("javascript:alert");
      expect(html).not.toContain("<a ");
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

    describe("isHeartbeatStale (client-side staleness against the panel's live clock)", () => {
      it("is false when now is null (SSR / before the mount effect resolves)", () => {
        const build = buildEntry({ state: "running", heartbeatAt: Date.now() - 10 * 60 * 1000 });
        expect(isHeartbeatStale(build, null)).toBe(false);
      });

      it("is false when there is no heartbeatAt (e.g. still claimed, pre-running)", () => {
        const build = buildEntry({ state: "running", heartbeatAt: undefined });
        expect(isHeartbeatStale(build, Date.now())).toBe(false);
      });

      it("is false just under the 3-minute threshold", () => {
        const now = Date.now();
        const build = buildEntry({ state: "running", heartbeatAt: now - (3 * 60 * 1000 - 1) });
        expect(isHeartbeatStale(build, now)).toBe(false);
      });

      it("is true just over the 3-minute threshold", () => {
        const now = Date.now();
        const build = buildEntry({ state: "running", heartbeatAt: now - (3 * 60 * 1000 + 1) });
        expect(isHeartbeatStale(build, now)).toBe(true);
      });

      it("advances from false to true as `now` moves forward without any new heartbeatAt — the exact scenario a died builder produces (no further fs.watch event, so no fresh collect)", () => {
        const heartbeatAt = Date.now();
        const build = buildEntry({ state: "running", heartbeatAt });
        expect(isHeartbeatStale(build, heartbeatAt + 60 * 1000)).toBe(false);
        expect(isHeartbeatStale(build, heartbeatAt + 4 * 60 * 1000)).toBe(true);
      });
    });
  });

  // L2-WU7 DEFECT B: the POST /api/queue response's `build` field
  // ({claimed:true}|{alreadyClaimed:true}|{error:"invalid_name"|"wrapper_not_found"})
  // was previously discarded entirely by postDecision, which collapsed the
  // whole response down to {ok:true}|{ok:false,error}. These tests exercise
  // postDecision directly against a mocked global.fetch (vitest's "node"
  // environment has native fetch, no jsdom needed) to prove the richer
  // response shape is now threaded through rather than dropped.
  describe("postDecision (L2-WU7 DEFECT B: build field must be threaded through, not discarded)", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function mockFetchOnce(body: unknown, status = 200) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: status >= 200 && status < 300,
          status,
          json: async () => body,
        })
      );
    }

    it("returns build:{claimed:true} verbatim when the server reports a successful claim", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: true, runId: "abcd1234" } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: true, runId: "abcd1234" },
      });
    });

    it("returns build:{error:'wrapper_not_found'} verbatim (the exact L2-WU7 DEFECT A server-side symptom) rather than silently succeeding", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: false, error: "wrapper_not_found" } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "wrapper_not_found" },
      });
    });

    it("returns build:{alreadyClaimed:true} verbatim", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: false, alreadyClaimed: true } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: false, alreadyClaimed: true },
      });
    });

    it("returns ok:true with no build field for a denied decision (no build field in the response at all)", async () => {
      mockFetchOnce({ hash: "h1", status: "denied" });
      const result = await postDecision("t", "h1", "denied");
      expect(result).toEqual({ ok: true, status: "denied", build: undefined });
    });

    it("still returns ok:false with the server error on a non-2xx response (unchanged behavior)", async () => {
      mockFetchOnce({ error: "unknown queue entry" }, 404);
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "unknown queue entry" });
    });

    it("still returns ok:false with 'network error' when fetch itself rejects (unchanged behavior)", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "network error" });
    });

    it("returns a distinct 'malformed server response' (not 'network error') when a 2xx body fails to parse", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => {
            throw new SyntaxError("Unexpected token < in JSON");
          },
        })
      );
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "malformed server response" });
    });

    it("returns 'malformed server response' for a 2xx body whose status is off-contract, rather than fabricating an 'approved' the server never asserted", async () => {
      mockFetchOnce({ hash: "h1", status: "pending" });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "malformed server response" });
    });
  });

  // L2-WU7 DEFECT B: AssistantLinkPanel previously gave zero visible
  // feedback after an Approve/Deny click — success, failure, and reason
  // were all indistinguishable from "nothing happened yet". These exercise
  // renderDecisionFeedback (the pure function the panel now calls with the
  // per-hash outcome of postDecision) directly via SSR.
  describe("renderDecisionFeedback (L2-WU7 DEFECT B: panel must show the outcome, not stay silent)", () => {
    function renderFeedback(feedback: Parameters<typeof renderDecisionFeedback>[0]) {
      return renderToStaticMarkup(createElement("div", null, renderDecisionFeedback(feedback)));
    }

    it("renders nothing when there is no feedback yet (fresh row, never clicked)", () => {
      const html = renderFeedback(undefined);
      expect(html).toBe("<div></div>");
    });

    it("shows 'build claimed — starting…' when the response reports build.claimed=true", () => {
      const html = renderFeedback({ ok: true, status: "approved", build: { claimed: true, runId: "abcd1234" } });
      expect(html).toContain("build claimed");
      expect(html).toContain("starting");
    });

    it("shows the build error verbatim, visibly, when build.error is present (the exact L2-WU7 DEFECT A symptom: wrapper_not_found)", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "wrapper_not_found" },
      });
      expect(html).toContain("build failed to start");
      expect(html).toContain("wrapper_not_found");
    });

    it("shows the invalid_name build error verbatim too (not just wrapper_not_found)", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "invalid_name" },
      });
      expect(html).toContain("build failed to start");
      expect(html).toContain("invalid_name");
    });

    it("shows an 'already claimed' message when build.alreadyClaimed=true", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, alreadyClaimed: true },
      });
      expect(html).toContain("already claimed");
    });

    it("shows a plain 'approved' confirmation when approved with no build field at all (non-workflow-audit entries never get a build field)", () => {
      const html = renderFeedback({ ok: true, status: "approved", build: undefined });
      expect(html).toContain(">approved<");
      expect(html).not.toContain("claimed");
    });

    it("shows a 'denied' confirmation for a denied decision, with no build-outcome language at all (negative control)", () => {
      const html = renderFeedback({ ok: true, status: "denied", build: undefined });
      expect(html).toContain(">denied<");
      expect(html).not.toContain("claimed");
      expect(html).not.toContain(">approved<");
    });

    it("shows the raw error message when the request itself failed (network/HTTP error, unchanged from prior error-surfacing behavior)", () => {
      const html = renderFeedback({ ok: false, error: "unknown queue entry" });
      expect(html).toContain("unknown queue entry");
    });
  });
});
