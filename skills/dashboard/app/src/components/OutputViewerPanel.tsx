"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { runResultLabel, formatDuration, formatHHMM } from "@/hooks/useDashboardState";
import type { RunRecord } from "@/lib/runlog";

export interface OutputViewerPanelProps {
  token: string;
}

// Picks which run the panel shows before the user has clicked anything: a still-active run (no
// endedAt) takes priority over any finished run regardless of start time — that's the run whose
// output is actually changing right now. With no active run, falls back to the most recently
// started run so there's always something useful to show. Pure and exported so the selection
// rule is unit-testable without mounting the component (SSR renders with no click simulation
// available — see AssistantLinkPanel.test.ts's equivalent pure-function extractions).
export function selectDefaultRunId(runs: RunRecord[]): string | undefined {
  const active = runs.find((r) => r.endedAt === undefined);
  if (active) return active.runId;
  if (runs.length === 0) return undefined;
  return runs.reduce((newest, r) => (r.startedAt > newest.startedAt ? r : newest)).runId;
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

// The COMMAND DECK's output-viewer: shows a run's output as it streams (live, via the
// "run-output" SSE event accumulated in DashboardState.runOutput — see useDashboardState.ts) and,
// once a run ends, its full settled output fetched from GET /api/run/output. Run-history rows are
// clickable to switch which run is shown; the default selection prefers whatever run is currently
// active. Matches RailRight's Command Deck aesthetic (same hud-block/hud-sec-head/hud-run-row
// classes) since this panel is the CTA gap that block's footnote ("Runner Executes") pointed at.
export function OutputViewerPanel({ token }: OutputViewerPanelProps) {
  const { snapshot, runOutput } = useDashboardContext();
  const { runs } = snapshot;
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);
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

  const effectiveRunId = selectedRunId ?? selectDefaultRunId(runs);
  const selectedRun = runs.find((r) => r.runId === effectiveRunId);
  const isLive = selectedRun !== undefined && selectedRun.endedAt === undefined;
  const finishedRunId = selectedRun !== undefined && !isLive ? selectedRun.runId : undefined;

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

  const settledError = selectedRun !== undefined && !isLive ? errorByRunId[selectedRun.runId] : undefined;
  const output = selectedRun === undefined ? undefined : isLive ? (runOutput[selectedRun.runId] ?? "") : settledByRunId[selectedRun.runId];

  return (
    <div className="hud-block">
      <div className="hud-sec-head">
        <span className="hud-title">Run Output</span>
        <span className="hud-suffix">{isLive ? "Live" : "Settled"}</span>
        <span className="hud-rule" />
      </div>

      {runs.length > 0 ? (
        <div className="hud-run-history">
          {runs.map((run) => {
            const result = runResultLabel(run);
            const duration = run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…";
            // Glyph-derivation logic duplicated intentionally from RailRight.tsx — keep both
            // mappings in sync if either changes.
            const glyphClass = result === "PASS" ? "status-ok" : result === "FAIL" ? "status-fail" : "";
            const glyph = result === "PASS" ? "◆" : result === "FAIL" ? "◇" : "·";
            return (
              <button
                type="button"
                key={run.runId}
                className={`hud-run-row hud-run-row-selectable${run.runId === effectiveRunId ? " selected" : ""}`}
                onClick={() => setSelectedRunId(run.runId)}
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

      {settledError !== undefined && finishedRunId !== undefined ? (
        <div className="hud-cmd-error">
          couldn&apos;t load output — {settledError}{" "}
          <button type="button" onClick={() => retry(finishedRunId)}>
            retry
          </button>
        </div>
      ) : (
        <pre className="hud-output-viewer">
          {output !== undefined && output !== "" ? output : "no output"}
        </pre>
      )}
    </div>
  );
}
