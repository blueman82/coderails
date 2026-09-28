import { formatRelativeAge } from "@/hooks/useDashboardState";
import type { QueueEntry } from "@/lib/collect/queue";
import type { BuildEntry } from "@/lib/collect/builds";
import { renderBuildStatus } from "./AssistantBuildStatus";
import { renderDecisionFeedback, type PostDecisionResult } from "./AssistantDecisions";
import { isWorkflowAuditProposal, previewToolInput, renderWorkflowAuditProposal } from "./AssistantQueueContent";

interface PendingApprovalRowProps {
  entry: QueueEntry;
  now: number | null;
  pending: boolean | undefined;
  feedback: PostDecisionResult | undefined;
  onDecision: (hash: string, decision: "approved" | "denied") => Promise<void>;
}

export function PendingApprovalRow({ entry, now, pending, feedback, onDecision }: PendingApprovalRowProps) {
  return (
          <div className="hud-gate-row" >
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
                disabled={pending}
                onClick={() => void onDecision(entry.hash, "approved")}
              >
                Approve
              </button>
              <button
                type="button"
                className="hud-queue-deny"
                disabled={pending}
                onClick={() => void onDecision(entry.hash, "denied")}
              >
                Deny
              </button>
            </div>
            {renderDecisionFeedback(feedback)}
          </div>
  );
}

interface BuildingApprovalRowProps {
  entry: QueueEntry;
  build: BuildEntry | undefined;
  now: number | null;
  openPrNumbers: ReadonlySet<number> | null;
}

export function BuildingApprovalRow({ entry, build, now, openPrNumbers }: BuildingApprovalRowProps) {
  return (
          <div className="hud-gate-row" >
            <div className="hud-gate-top">
              <span>{entry.toolName}</span>
            </div>
            {isWorkflowAuditProposal(entry.toolInput) ? (
              <div className="hud-queue-proposal-name">{entry.toolInput.proposed_name}</div>
            ) : null}
            {renderBuildStatus(build, now, openPrNumbers)}
          </div>
  );
}
