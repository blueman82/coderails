import type { ClaimAndSpawnBuildResult } from "@/lib/build/spawn";

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
