"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { runResultLabel, formatDuration, formatHHMM } from "@/hooks/useDashboardState";
import { projectAssistantText } from "@/lib/streamJson";
import { RunOutputOverlay } from "@/components/RunOutputOverlay";

export interface OutputViewerPanelProps {
  token: string;
}

// Discriminated result mirroring AssistantLinkPanel.tsx's postDecision — every failure mode
// (network error, non-2xx status, malformed JSON) carries enough information for the caller to
// show a distinct, visible failure state instead of collapsing to the same "no output" a
// genuinely empty run produces. "in-progress" is its own case (not an error): the route returns
// 409 for a live run's record rather than a partial read (see api/run/output/route.ts) — the
// caller already has the correct data for that case via the live SSE buffer, so it's surfaced
// distinctly rather than folded into "error".
export type SettledOutputResult =
  | { ok: true; output: string }
  | { ok: false; kind: "in-progress" }
  | { ok: false; kind: "error"; error: string };

export async function fetchSettledOutput(token: string, runId: string): Promise<SettledOutputResult> {
  let res: Response;
  try {
    res = await fetch(`/api/run/output?runId=${encodeURIComponent(runId)}&token=${encodeURIComponent(token)}`);
  } catch {
    return { ok: false, kind: "error", error: "network error" };
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return { ok: false, kind: "error", error: `malformed response (${res.status})` };
  }
  const parsed = body as { status?: unknown; output?: unknown; error?: unknown };
  if (res.status === 409 || parsed.status === "in-progress") {
    return { ok: false, kind: "in-progress" };
  }
  if (res.ok && typeof parsed.output === "string") {
    return { ok: true, output: parsed.output };
  }
  const error = typeof parsed.error === "string" ? parsed.error : `request failed (${res.status})`;
  return { ok: false, kind: "error", error };
}

// The COMMAND DECK's run-output history box: lists every run (glyph · button · result · id ·
// duration · time) as a clickable row. Clicking a row opens an in-page OVERLAY (RunOutputOverlay)
// that renders the run's output as sanitized markdown — the retired inline <pre> viewer squished
// that same text into a small box below this list, which is what Task T10 replaced. This panel
// still owns the data flow the overlay consumes: the live SSE buffer (DashboardState.runOutput,
// projected from raw stream-json to prose) for an in-flight run, and the settled fetch
// (GET /api/run/output, already server-extracted prose) cached per finished run.
export function OutputViewerPanel({ token }: OutputViewerPanelProps) {
  const { snapshot, runOutput } = useDashboardContext();
  const { runs } = snapshot;
  // Which run's overlay is open. undefined = overlay closed (the default — nothing shows until a
  // row is clicked, so there's no inline region to scroll past). A run that leaves the `runs`
  // snapshot entirely closes its overlay (see effect below).
  const [openRunId, setOpenRunId] = useState<string | undefined>(undefined);
  // Cache of fetched settled output, keyed by runId — fetched once per finished run, never
  // refetched just because the panel re-renders (a finished run's output file never changes).
  const [settledByRunId, setSettledByRunId] = useState<Record<string, string>>({});
  // Failed-fetch errors, keyed by runId — same shape as AssistantLinkPanel.tsx's `errors` state.
  // A failure never writes into settledByRunId, so it must be tracked separately: otherwise a
  // failed fetch would be indistinguishable from "not yet fetched" and the caller couldn't show
  // a distinct message, nor could a later retry tell "still pending" apart from "already tried
  // and failed".
  const [errorByRunId, setErrorByRunId] = useState<Record<string, string>>({});
  // Mirrors settledByRunId/errorByRunId for the fetch effect below to consult without depending
  // on the state values themselves (a dependency on either would re-run that effect the instant
  // it writes to that state, since the write is what the dependency array would be watching) —
  // updated in its own effect, same pattern as useRunLifecycle.ts's runsRef.
  const settledByRunIdRef = useRef(settledByRunId);
  const errorByRunIdRef = useRef(errorByRunId);
  useEffect(() => {
    settledByRunIdRef.current = settledByRunId;
  }, [settledByRunId]);
  useEffect(() => {
    errorByRunIdRef.current = errorByRunId;
  }, [errorByRunId]);

  // The open run, looked up in the current snapshot. If the open run drops out of the snapshot
  // (e.g. the run list is trimmed), this is undefined and the overlay simply doesn't render —
  // no state reset needed, and the stale `openRunId` is harmless (it matches no row, so no row
  // shows as selected, and a later click overwrites it).
  const openRun = runs.find((r) => r.runId === openRunId);

  const isLive = openRun !== undefined && openRun.endedAt === undefined;
  const finishedRunId = openRun !== undefined && !isLive ? openRun.runId : undefined;

  // Shared by the auto-fetch effect below and the manual retry button: runs the fetch for one
  // runId and files the result into whichever cache applies. Not itself an effect so the retry
  // button can invoke it directly and get an immediate in-flight fetch, rather than only clearing
  // state and hoping a dependency change fires the effect again. Wrapped in useCallback (deps:
  // just `token`, the only external value it closes over besides the setters, which React
  // guarantees are stable) so it has a stable identity the effect below can honestly depend on.
  const loadSettledOutput = useCallback(
    (runId: string, isCancelled: () => boolean) => {
      void fetchSettledOutput(token, runId).then((result) => {
        if (isCancelled()) return;
        if (result.ok) {
          setSettledByRunId((prev) => ({ ...prev, [runId]: result.output }));
          return;
        }
        if (result.kind === "in-progress") {
          // The record hasn't caught up to endedAt yet (race between the "runs" snapshot and the
          // route's own read of runs.jsonl) — not a real failure, just not ready. Leave both
          // caches untouched so the effect retries next time finishedRunId/token changes (e.g. a
          // fresh "runs" snapshot arrives and re-renders the panel).
          return;
        }
        setErrorByRunId((prev) => ({ ...prev, [runId]: result.error }));
      });
    },
    [token]
  );

  useEffect(() => {
    if (!finishedRunId) return;
    if (settledByRunIdRef.current[finishedRunId] !== undefined) return;
    if (errorByRunIdRef.current[finishedRunId] !== undefined) return;
    let cancelled = false;
    loadSettledOutput(finishedRunId, () => cancelled);
    return () => {
      cancelled = true;
    };
  }, [finishedRunId, loadSettledOutput]);

  function retry(runId: string) {
    setErrorByRunId((prev) => {
      const next = { ...prev };
      delete next[runId];
      return next;
    });
    loadSettledOutput(runId, () => false);
  }

  const settledError = finishedRunId !== undefined ? errorByRunId[finishedRunId] : undefined;
  // The raw output string feeding the overlay: for a live run it's the live SSE buffer (raw
  // stream-json, projected to clean prose — the buffer is hundreds of JSON lines otherwise); for
  // a settled run it's the server-extracted prose from GET /api/run/output. Both ultimately feed
  // the same markdown renderer in the overlay.
  const openOutput =
    openRun === undefined
      ? undefined
      : isLive
        ? projectAssistantText(runOutput[openRun.runId] ?? "")
        : settledByRunId[openRun.runId];

  return (
    <div className="hud-block">
      <div className="hud-sec-head">
        <span className="hud-title">Run Output</span>
        <span className="hud-suffix">History</span>
        <span className="hud-rule" />
      </div>

      {runs.length > 0 ? (
        <div className="hud-run-history">
          {runs.map((run) => {
            const result = runResultLabel(run);
            const duration = run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…";
            // Result -> glyph/class mapping: PASS -> filled diamond, FAIL -> hollow diamond,
            // anything else (still running) -> a plain dot.
            const glyphClass = result === "PASS" ? "status-ok" : result === "FAIL" ? "status-fail" : "";
            const glyph = result === "PASS" ? "◆" : result === "FAIL" ? "◇" : "·";
            return (
              <button
                type="button"
                key={run.runId}
                className={`hud-run-row hud-run-row-selectable${run.runId === openRunId ? " selected" : ""}`}
                onClick={() => setOpenRunId(run.runId)}
              >
                <span>
                  <span className={`hud-glyph${glyphClass ? ` ${glyphClass}` : ""}`}>{glyph}</span>
                  {run.button.toUpperCase()} · {result} · {run.runId}
                </span>
                <span>
                  {duration} · {formatHHMM(run.startedAt)}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="hud-empty-state">no runs yet</div>
      )}

      {openRun !== undefined && (
        <RunOutputOverlay
          run={openRun}
          isLive={isLive}
          output={openOutput}
          error={settledError}
          onRetry={finishedRunId !== undefined ? () => retry(finishedRunId) : undefined}
          onClose={() => setOpenRunId(undefined)}
        />
      )}
    </div>
  );
}
