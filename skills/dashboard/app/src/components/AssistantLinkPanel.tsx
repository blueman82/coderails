"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   "now" (for relative-age formatting) is a genuinely client-only value (SSR has no "now"); it
   must resolve after mount via an effect — same shape as RailLeft.tsx's own "now" state. */

import { useState, useEffect } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import type { QueueEntry } from "@/lib/collect/queue";
import type { BuildEntry } from "@/lib/collect/builds";

export interface AssistantLinkPanelProps {
  token: string;
}

export { isHeartbeatStale, formatElapsed, renderBuildStatus } from "./AssistantBuildStatus";
export { postDecision, renderDecisionFeedback } from "./AssistantDecisions";
export type { PostDecisionResult } from "./AssistantDecisions";
import { postDecision, type PostDecisionResult } from "./AssistantDecisions";
import { PendingApprovalRow, BuildingApprovalRow } from "./AssistantQueueRows";

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
          <PendingApprovalRow key={entry.hash} entry={entry} now={now} pending={pending[entry.hash]}
            feedback={feedback[entry.hash]} onDecision={handleDecision} />
        ))
      ) : (
        <div className="hud-empty-state">no pending approvals</div>
      )}
      {buildingEntries.length > 0 &&
        buildingEntries.map(({ entry, build }) => (
          <BuildingApprovalRow key={entry.hash} entry={entry} build={build} now={now} openPrNumbers={openPrNumbers} />
        ))}
    </div>
  );
}
