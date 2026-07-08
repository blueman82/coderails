"use client";

import { useEffect, useRef, useState } from "react";
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

async function fetchSettledOutput(token: string, runId: string): Promise<string | undefined> {
  try {
    const res = await fetch(`/api/run/output?runId=${encodeURIComponent(runId)}&token=${encodeURIComponent(token)}`);
    if (!res.ok) return undefined;
    const body = (await res.json()) as { output?: unknown };
    return typeof body.output === "string" ? body.output : undefined;
  } catch {
    return undefined;
  }
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
  // Mirrors settledByRunId for the fetch effect below to consult without depending on the state
  // value itself (a dependency on settledByRunId would re-run that effect the instant it writes
  // to that state, since the write is what the dependency array would be watching) — updated in
  // its own effect, same pattern as useRunLifecycle.ts's runsRef.
  const settledByRunIdRef = useRef(settledByRunId);
  useEffect(() => {
    settledByRunIdRef.current = settledByRunId;
  }, [settledByRunId]);

  const effectiveRunId = selectedRunId ?? selectDefaultRunId(runs);
  const selectedRun = runs.find((r) => r.runId === effectiveRunId);
  const isLive = selectedRun !== undefined && selectedRun.endedAt === undefined;
  const finishedRunId = selectedRun !== undefined && !isLive ? selectedRun.runId : undefined;

  useEffect(() => {
    if (!finishedRunId) return;
    if (settledByRunIdRef.current[finishedRunId] !== undefined) return;
    let cancelled = false;
    void fetchSettledOutput(token, finishedRunId).then((output) => {
      if (cancelled || output === undefined) return;
      setSettledByRunId((prev) => ({ ...prev, [finishedRunId]: output }));
    });
    return () => {
      cancelled = true;
    };
  }, [finishedRunId, token]);

  const output = selectedRun === undefined ? undefined : isLive ? (runOutput[selectedRun.runId] ?? "") : settledByRunId[selectedRun.runId];

  return (
    <div className="hud-block">
      <div className="hud-sec-head">
        <span className="hud-title">Run Output</span>
        <span className="hud-suffix">{isLive ? "Live" : "Settled"}</span>
        <span className="hud-rule" />
      </div>

      {runs.length > 0 ? (
        <div className="hud-run-history hud-run-history-selectable">
          {runs.map((run) => {
            const result = runResultLabel(run);
            const duration = run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…";
            return (
              <button
                type="button"
                key={run.runId}
                className={`hud-run-row hud-run-row-selectable${run.runId === effectiveRunId ? " selected" : ""}`}
                onClick={() => setSelectedRunId(run.runId)}
              >
                <span>
                  <span className="hud-glyph">·</span>
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

      <pre className="hud-output-viewer">
        {output !== undefined && output !== "" ? output : "no output"}
      </pre>
    </div>
  );
}
