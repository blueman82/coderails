"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   "now" (for relative-age formatting) is a genuinely client-only value (SSR has no "now"); it
   must resolve after mount via an effect — same shape as RailLeft.tsx's own "now" state. */

import { useState, useEffect } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { formatRelativeAge } from "@/hooks/useDashboardState";
import type { QueueEntry } from "@/lib/collect/queue";
import type { BuildEntry } from "@/lib/collect/builds";

export interface AssistantLinkPanelProps {
  token: string;
}

// Heartbeat staleness threshold: run-builder.sh touches builds/<hash>/heartbeat
// every 30s (BUILDER_HEARTBEAT_SECS) while claude is running — 3 minutes of
// silence means the process died without writing a terminal state.
const HEARTBEAT_STALE_MS = 3 * 60 * 1000;

// Pure, exported so it's directly unit-testable without needing the
// component's mount effect to fire (this file's tests render via
// renderToStaticMarkup/SSR, where `now` is always null). `now` is the
// panel's own live clock, not a server-computed age: the builds dir's
// fs.watch only re-collects on a filesystem event, so a build that dies
// without writing a terminal state (SIGKILL, power loss — the one path that
// skips run-builder.sh's EXIT trap) stops touching the heartbeat file and
// triggers no further event at all. Comparing the heartbeat's absolute mtime
// against the client's own ticking `now` is what lets "builder dead" keep
// advancing after the last real collect, instead of freezing at whatever
// staleness happened to be true the moment collection stopped. `now === null`
// (SSR, or before the mount effect resolves) is treated as "not yet known" —
// never stale — same convention as formatRelativeAge's null-`now` handling.
export function isHeartbeatStale(build: BuildEntry, now: number | null): boolean {
  return build.heartbeatAt !== undefined && now !== null && now - build.heartbeatAt > HEARTBEAT_STALE_MS;
}

// prUrl is builder-session-controlled data (state.json, read verbatim from
// run-builder.sh's own `gh pr create` output — see builds.ts), not a value
// this dashboard itself generates. Rendered into an <a href>, an unvalidated
// scheme (javascript:, data:) would be a click-triggered XSS vector, so only
// an https: URL is ever linked; anything else falls back to the plain-text
// CTA, same as when prUrl is absent.
function safePrUrl(prUrl: string | undefined): string | undefined {
  if (!prUrl) return undefined;
  try {
    return new URL(prUrl).protocol === "https:" ? prUrl : undefined;
  } catch {
    return undefined;
  }
}

// Renders the build-state CTA for an approved workflow-audit:propose-skill
// queue entry, joined to its builds/<hash>/ sidecar by hash. Returns null
// when there's no build entry yet (claim hasn't landed on disk, or this
// approved entry predates the builder pipeline) — the row still renders,
// just without a build status line.
function renderBuildStatus(build: BuildEntry | undefined, now: number | null) {
  if (!build) return null;
  if (build.state === "pr_open") {
    const prUrl = safePrUrl(build.prUrl);
    return (
      <div className="hud-build-status hud-build-pr-open">
        {prUrl ? (
          <a href={prUrl} target="_blank" rel="noreferrer">
            PR open — awaiting your merge
          </a>
        ) : (
          "PR open — awaiting your merge"
        )}
      </div>
    );
  }
  if (build.state === "failed") {
    return (
      <div className="hud-build-status hud-build-failed">
        failed: {build.failureReason ?? "unknown"} — delete builds/{build.hash} to retry
      </div>
    );
  }
  if (build.state === "running") {
    const stale = isHeartbeatStale(build, now);
    return (
      <div className={`hud-build-status ${stale ? "hud-build-dead" : "hud-build-building"}`}>
        {stale ? "builder dead" : "building"}
      </div>
    );
  }
  // claimed | queued
  return <div className="hud-build-status hud-build-building">building</div>;
}

// Truncates JSON.stringify(toolInput) for display — this is the ONLY
// operation this component performs on toolInput. It is never destructured
// by assumed shape (per the queue contract's opacity rule: the queue is
// generic across all gated tools, so the panel can't assume a toolInput
// shape belongs to any particular tool).
const TOOL_INPUT_PREVIEW_MAX = 160;

function previewToolInput(toolInput: unknown): string {
  let json: string;
  try {
    json = JSON.stringify(toolInput);
  } catch {
    return "(unrenderable input)";
  }
  if (json === undefined) return "(unrenderable input)";
  return json.length > TOOL_INPUT_PREVIEW_MAX ? json.slice(0, TOOL_INPUT_PREVIEW_MAX) + "…" : json;
}

// One deliberate, named exception to the opacity rule above:
// "workflow-audit:propose-skill" carries a fixed, judge-contract-vetted
// six-field vocabulary (skills/workflow-audit/references/judge-contract.md)
// worth rendering legibly rather than as a truncated JSON blob. The type
// guard only recognizes that exact shape; anything else — including a
// malformed proposal missing a field — still falls through to the opaque
// previewToolInput() path above.
interface WorkflowAuditProposalInput {
  cluster_ngram: string[];
  count: number;
  sessions: string[];
  task_summary: string;
  proposed_name: string;
  proposed_description: string;
}

function isWorkflowAuditProposal(toolInput: unknown): toolInput is WorkflowAuditProposalInput {
  if (typeof toolInput !== "object" || toolInput === null) return false;
  const t = toolInput as Record<string, unknown>;
  return (
    Array.isArray(t.cluster_ngram) &&
    t.cluster_ngram.every((s) => typeof s === "string") &&
    typeof t.count === "number" &&
    Array.isArray(t.sessions) &&
    t.sessions.every((s) => typeof s === "string") &&
    typeof t.task_summary === "string" &&
    typeof t.proposed_name === "string" &&
    typeof t.proposed_description === "string"
  );
}

function renderWorkflowAuditProposal(input: WorkflowAuditProposalInput) {
  return (
    <div className="hud-queue-proposal-preview">
      <div className="hud-queue-proposal-name">{input.proposed_name}</div>
      <div className="hud-queue-proposal-description">{input.proposed_description}</div>
      <div className="hud-queue-proposal-summary">{input.task_summary}</div>
      <div className="hud-queue-proposal-stats">
        {input.count} occurrences / {input.sessions.length} sessions
      </div>
      <div className="hud-queue-proposal-chain">{input.cluster_ngram.join(" → ")}</div>
    </div>
  );
}

async function postDecision(
  token: string,
  hash: string,
  decision: "approved" | "denied"
): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const res = await fetch("/api/queue", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, hash, decision }),
    });
    if (res.ok) return { ok: true };
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    return { ok: false, error: body.error ?? `request failed (${res.status})` };
  } catch {
    return { ok: false, error: "network error" };
  }
}

// ASSISTANT.LINK panel, item 3 ("Sends + approvals log") — the pending-queue
// slice only. Per docs/coderails/specs/2026-07-06-assistant-link-panel-design.md,
// the other three panel slots (tasks, email-checked, routine-runs) are
// explicitly out of scope for this component; they are not rendered here.
export function AssistantLinkPanel({ token }: AssistantLinkPanelProps) {
  const { snapshot } = useDashboardContext();
  const { queue, builds } = snapshot;
  const [now, setNow] = useState<number | null>(null);
  // Tracks hashes currently mid-request so a double-click can't fire twice,
  // and clears once the queue snapshot itself confirms the entry left
  // "pending" (or the request failed) — same optimistic-flag shape as
  // RailRight's `queued` state, scoped down to what this panel needs.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const pendingEntries: QueueEntry[] = queue.filter((e) => e.status === "pending");
  // Approved workflow-audit:propose-skill entries with a build already
  // claimed on disk — joined to their builds/<hash>/ sidecar by hash. An
  // approved entry with no build entry yet (claim hasn't landed, or predates
  // this feature) renders nothing here; there's no status to show.
  const buildingEntries: { entry: QueueEntry; build: BuildEntry }[] = queue
    .filter((e) => e.status === "approved" && e.toolName === "workflow-audit:propose-skill")
    .map((entry) => ({ entry, build: builds.find((b) => b.hash === entry.hash) }))
    .filter((x): x is { entry: QueueEntry; build: BuildEntry } => x.build !== undefined);

  async function handleDecision(hash: string, decision: "approved" | "denied") {
    if (pending[hash]) return;
    setPending((prev) => ({ ...prev, [hash]: true }));
    setErrors((prev) => ({ ...prev, [hash]: "" }));
    const result = await postDecision(token, hash, decision);
    setPending((prev) => ({ ...prev, [hash]: false }));
    if (!result.ok) {
      setErrors((prev) => ({ ...prev, [hash]: result.error }));
    }
  }

  return (
    <div className="hud-block">
      <div className="hud-sec-head">
        <span className="hud-title">Assistant.Link</span>
        <span className="hud-suffix">Approvals</span>
        <span className="hud-rule" />
      </div>
      {pendingEntries.length > 0 ? (
        pendingEntries.map((entry) => (
          <div className="hud-gate-row" key={entry.hash}>
            <div className="hud-gate-top">
              <span>{entry.toolName}</span>
            </div>
            <div className="hud-gate-status">
              <span className="hud-diamond">◇</span>
              {now ? formatRelativeAge(entry.createdAt, now) : ""}
            </div>
            {entry.toolName === "workflow-audit:propose-skill" && isWorkflowAuditProposal(entry.toolInput) ? (
              renderWorkflowAuditProposal(entry.toolInput)
            ) : (
              <pre className="hud-queue-input-preview">{previewToolInput(entry.toolInput)}</pre>
            )}
            <div className="hud-queue-actions">
              <button
                type="button"
                className="hud-queue-approve"
                disabled={pending[entry.hash]}
                onClick={() => void handleDecision(entry.hash, "approved")}
              >
                Approve
              </button>
              <button
                type="button"
                className="hud-queue-deny"
                disabled={pending[entry.hash]}
                onClick={() => void handleDecision(entry.hash, "denied")}
              >
                Deny
              </button>
            </div>
            {errors[entry.hash] && <div className="hud-cmd-error">{errors[entry.hash]}</div>}
          </div>
        ))
      ) : (
        <div className="hud-empty-state">no pending approvals</div>
      )}
      {buildingEntries.length > 0 &&
        buildingEntries.map(({ entry, build }) => (
          <div className="hud-gate-row" key={entry.hash}>
            <div className="hud-gate-top">
              <span>{entry.toolName}</span>
            </div>
            {isWorkflowAuditProposal(entry.toolInput) ? (
              <div className="hud-queue-proposal-name">{entry.toolInput.proposed_name}</div>
            ) : null}
            {renderBuildStatus(build, now)}
          </div>
        ))}
    </div>
  );
}
