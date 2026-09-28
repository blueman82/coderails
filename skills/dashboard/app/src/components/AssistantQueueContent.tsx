// Truncates JSON.stringify(toolInput) for display — this is the ONLY
// operation this component performs on toolInput. It is never destructured
// by assumed shape (per the queue contract's opacity rule: the queue is
// generic across all gated tools, so the panel can't assume a toolInput
// shape belongs to any particular tool).
const TOOL_INPUT_PREVIEW_MAX = 160;

export function previewToolInput(toolInput: unknown): string {
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

export function isWorkflowAuditProposal(toolInput: unknown): toolInput is WorkflowAuditProposalInput {
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

export function renderWorkflowAuditProposal(input: WorkflowAuditProposalInput) {
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
