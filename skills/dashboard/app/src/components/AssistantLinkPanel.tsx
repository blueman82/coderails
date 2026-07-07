"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   "now" (for relative-age formatting) is a genuinely client-only value (SSR has no "now"); it
   must resolve after mount via an effect — same shape as RailLeft.tsx's own "now" state. */

import { useState, useEffect } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { formatRelativeAge } from "@/hooks/useDashboardState";
import type { QueueEntry } from "@/lib/collect/queue";

export interface AssistantLinkPanelProps {
  token: string;
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
  const { queue } = snapshot;
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
            <pre className="hud-queue-input-preview">{previewToolInput(entry.toolInput)}</pre>
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
    </div>
  );
}
