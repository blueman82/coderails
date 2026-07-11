"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   "now" (for relative-age formatting) is a genuinely client-only value (SSR has no "now"); it
   must resolve after mount via an effect — same shape as RailLeft.tsx's own "now" state. */

import { useState, useEffect } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { formatRelativeAge } from "@/hooks/useDashboardState";
import type { QueueEntry } from "@/lib/collect/queue";
import type { BuildEntry } from "@/lib/collect/builds";
import type { ClaimAndSpawnBuildResult } from "@/lib/build/spawn";

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
// queue entry, joined to its builds/<hash>/ sidecar by hash. When there's no
// build entry yet — the claim never landed on disk (e.g. L2-WU7 DEFECT A's
// wrapper_not_found), or this approved entry predates the builder pipeline —
// this renders an explicit "no build claimed" line rather than nothing, so
// the owner's genuine Approve click isn't followed by silence (L2-WU7
// DEFECT B).
// Human-readable elapsed time from a start epoch-ms against the client's
// live `now`. Returns "" when either input is unknown (SSR before mount, or
// a build with no startedAt) so the caller renders no elapsed fragment
// rather than "NaN" — same null-`now` convention as formatRelativeAge.
export function formatElapsed(startedAt: number | undefined, now: number | null): string {
  if (startedAt === undefined || now === null) return "";
  const totalSec = Math.max(0, Math.floor((now - startedAt) / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m${s}s` : `${s}s`;
}

// Parses the trailing PR number out of a builder-written prUrl
// (…/pull/<n>). Returns undefined for any URL that doesn't end in a numeric
// pull path — so a malformed prUrl simply doesn't participate in the
// open-PR-set join rather than throwing.
function prNumberFromUrl(prUrl: string | undefined): number | undefined {
  if (!prUrl) return undefined;
  const m = /\/pull\/(\d+)(?:$|[/?#])/.exec(prUrl);
  if (!m) return undefined;
  const n = Number(m[1]);
  return Number.isInteger(n) ? n : undefined;
}

// openPrNumbers is the set of currently-open PR numbers the dashboard
// already collects (prGates lists only open PRs). It lets a pr_open build
// reconcile after the fact: if its PR is no longer in the open set, it was
// merged or closed, so the panel stops claiming "awaiting your merge" — the
// after-merge staleness the owner hit when a merge left the build showing a
// stale status.
//
// NULL means "the open-PR set is not trustworthy right now" — gates haven't
// loaded yet (they arrive via a separate, slower `gh pr list` fetch than the
// synchronous builds slice), the gate poll failed, or this build's repo
// degraded to an error entry. In every such case an actually-open PR would
// be ABSENT from an empty/partial set and falsely read as "resolved" — the
// exact stale-status class inverted. When null, the reconciliation is
// skipped and the build shows the plain "awaiting your merge" until a
// trustworthy set arrives.
export function renderBuildStatus(
  build: BuildEntry | undefined,
  now: number | null,
  openPrNumbers: ReadonlySet<number> | null
) {
  if (!build) {
    return (
      <div className="hud-build-status hud-build-failed">
        approved — no build claimed (see server)
      </div>
    );
  }
  if (build.state === "pr_open") {
    const prUrl = safePrUrl(build.prUrl);
    const prNumber = prNumberFromUrl(build.prUrl);
    // Only downgrade to "resolved" when the open-PR set is trustworthy
    // (non-null). A null set (gates unloaded/failed/degraded) leaves the
    // build showing "awaiting your merge" rather than a false "resolved".
    const resolved = openPrNumbers !== null && prNumber !== undefined && !openPrNumbers.has(prNumber);
    const label = resolved ? "PR resolved — merged or closed" : "PR open — awaiting your merge";
    return (
      <div className={`hud-build-status ${resolved ? "hud-build-resolved" : "hud-build-pr-open"}`}>
        {prUrl ? (
          <a href={prUrl} target="_blank" rel="noreferrer">
            {label}
          </a>
        ) : (
          label
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
    const elapsed = formatElapsed(build.startedAt, now);
    const heartbeatAge =
      build.heartbeatAt !== undefined && now !== null ? formatRelativeAge(build.heartbeatAt, now) : "";
    const label = stale ? "builder dead" : build.phase ? `building · ${build.phase}` : "building";
    const detail = [elapsed, heartbeatAge ? `last active ${heartbeatAge}` : ""]
      .filter(Boolean)
      .join(" · ");
    return (
      <div className={`hud-build-status ${stale ? "hud-build-dead" : "hud-build-building"}`}>
        {label}
        {detail ? <span className="hud-build-detail"> {detail}</span> : null}
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

// L2-WU7 DEFECT B: previously collapsed the whole POST /api/queue response
// down to {ok:true}|{ok:false,error}, discarding the response's `status` and
// `build` fields entirely — so an owner's Approve click that hit
// wrapper_not_found on the server looked identical to a successful claim.
// Threads both fields through verbatim instead (D2: no fields invented
// beyond what route.ts's jsonResponse actually returns).
export type PostDecisionResult =
  | { ok: true; status: "approved" | "denied"; build: ClaimAndSpawnBuildResult | undefined }
  | { ok: false; error: string };

export async function postDecision(
  token: string,
  hash: string,
  decision: "approved" | "denied"
): Promise<PostDecisionResult> {
  try {
    const res = await fetch("/api/queue", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, hash, decision }),
    });
    if (res.ok) {
      // A 2xx with an unparseable or off-contract body must not masquerade as a
      // successful "approved" (the very silence this panel exists to end): guard
      // the parse the same way the error path below does, and only trust `status`
      // if it is one of the two shapes route.ts's jsonResponse actually returns.
      const body = (await res.json().catch(() => null)) as
        | { status?: unknown; build?: ClaimAndSpawnBuildResult }
        | null;
      if (body === null || (body.status !== "approved" && body.status !== "denied")) {
        return { ok: false, error: "malformed server response" };
      }
      return { ok: true, status: body.status, build: body.build };
    }
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    return { ok: false, error: body.error ?? `request failed (${res.status})` };
  } catch {
    return { ok: false, error: "network error" };
  }
}

// Renders the outcome of a completed Approve/Deny click on the row itself —
// pure and exported so it's directly unit-testable via SSR the same way
// renderBuildStatus above is. Previously handleDecision only ever surfaced
// network/HTTP-level errors (result.ok === false); a successful response
// whose build field carried claimed:false was rendered as if nothing had
// happened at all (L2-WU7 DEFECT B). Returns null when there's no feedback
// yet (fresh row, never clicked) — the row's normal content shows instead.
export function renderDecisionFeedback(feedback: PostDecisionResult | undefined) {
  if (!feedback) return null;
  if (!feedback.ok) {
    return <div className="hud-cmd-error">{feedback.error}</div>;
  }
  if (feedback.status === "denied") {
    return <div className="hud-build-status hud-build-building">denied</div>;
  }
  // approved
  if (!feedback.build) {
    return <div className="hud-build-status hud-build-building">approved</div>;
  }
  if (feedback.build.claimed) {
    return <div className="hud-build-status hud-build-building">build claimed — starting…</div>;
  }
  if ("alreadyClaimed" in feedback.build) {
    return <div className="hud-build-status hud-build-building">approved — build already claimed</div>;
  }
  return (
    <div className="hud-cmd-error">build failed to start: {feedback.build.error}</div>
  );
}

// ASSISTANT.LINK panel, item 3 ("Sends + approvals log") — the pending-queue
// slice only. The other three panel slots (tasks, email-checked, routine-runs)
// are explicitly out of scope for this component; they are not rendered here.
export function AssistantLinkPanel({ token }: AssistantLinkPanelProps) {
  const { snapshot } = useDashboardContext();
  const { queue, builds, gates } = snapshot;
  // The set of currently-open PR numbers, from the prGates collector (which
  // lists only open PRs). A pr_open build whose PR is absent here has been
  // merged or closed — see renderBuildStatus's after-merge reconciliation.
  //
  // NULL when the set can't be trusted: gates haven't loaded yet (empty on
  // first paint, before the separate gh-pr-list fetch resolves) or a repo
  // degraded to an error entry (its open PRs would be missing). Passing null
  // makes renderBuildStatus skip the reconciliation rather than falsely mark
  // an open PR "resolved" — the inverse stale-status the review caught.
  const gatesTrustworthy = gates.length > 0 && gates.every((g) => "number" in g);
  const openPrNumbers: ReadonlySet<number> | null = gatesTrustworthy
    ? new Set<number>(
        gates.flatMap((g) => ("number" in g && typeof g.number === "number" ? [g.number] : []))
      )
    : null;
  const [now, setNow] = useState<number | null>(null);
  // Tracks hashes currently mid-request so a double-click can't fire twice,
  // and clears once the queue snapshot itself confirms the entry left
  // "pending" (or the request failed) — same optimistic-flag shape as
  // RailRight's `queued` state, scoped down to what this panel needs.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  // Per-hash outcome of the most recent Approve/Deny click, rendered via
  // renderDecisionFeedback — see its comment for why this exists
  // (L2-WU7 DEFECT B: the panel previously gave zero feedback either way).
  const [feedback, setFeedback] = useState<Record<string, PostDecisionResult | undefined>>({});

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const pendingEntries: QueueEntry[] = queue.filter((e) => e.status === "pending");
  // Approved workflow-audit:propose-skill entries, joined to their
  // builds/<hash>/ sidecar by hash where one exists. An approved entry with
  // no build entry yet (claim hasn't landed — e.g. the L2-WU7 DEFECT A
  // wrapper_not_found case — or the entry predates this feature) still gets
  // a row here with an explicit "no build claimed" state, rather than
  // rendering nothing (silent-failure-hunter finding, L2-WU7 DEFECT B).
  const buildingEntries: { entry: QueueEntry; build: BuildEntry | undefined }[] = queue
    .filter((e) => e.status === "approved" && e.toolName === "workflow-audit:propose-skill")
    .map((entry) => ({ entry, build: builds.find((b) => b.hash === entry.hash) }));

  async function handleDecision(hash: string, decision: "approved" | "denied") {
    if (pending[hash]) return;
    setPending((prev) => ({ ...prev, [hash]: true }));
    setFeedback((prev) => ({ ...prev, [hash]: undefined }));
    const result = await postDecision(token, hash, decision);
    setPending((prev) => ({ ...prev, [hash]: false }));
    setFeedback((prev) => ({ ...prev, [hash]: result }));
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
            {renderDecisionFeedback(feedback[entry.hash])}
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
            {renderBuildStatus(build, now, openPrNumbers)}
          </div>
        ))}
    </div>
  );
}
