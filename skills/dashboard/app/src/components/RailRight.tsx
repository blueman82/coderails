"use client";

import { useDashboardState, formatDuration, formatHHMM, runResultLabel, isGateError } from "@/hooks/useDashboardState";

// Buttons stay static labels — Task 9d wires the run/click lifecycle onto these.
const COMMANDS = [
  { label: "Wiki Lint" },
  { label: "Sync Docs" },
  { label: "AM Report" },
  { label: "Deep Research" },
  { label: "PR Gates" },
  { label: "WK Review" },
];

export function RailRight() {
  const { snapshot } = useDashboardState();
  const { runs, gates } = snapshot;

  return (
    <section className="hud-rail hud-rail-right">
      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Command Deck</span>
          <span className="hud-rule" />
          <span className="hud-deck-status">Idle · 0/4 Active · 0 Queued</span>
        </div>

        <div className="hud-active-cmd-list" />

        <div className="hud-cmd-grid">
          {COMMANDS.map((cmd) => (
            <button className="hud-cmd" type="button" key={cmd.label}>
              <span className="hud-bullet" />
              <span className="hud-label">{cmd.label}</span>
            </button>
          ))}
        </div>

        <div className="hud-run-history">
          {runs.length > 0 ? (
            runs.map((run) => {
              const result = runResultLabel(run);
              const duration = run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…";
              return (
                <div className="hud-run-row" key={run.runId}>
                  <span>
                    <span className="hud-glyph">·</span>
                    {run.button.toUpperCase()} · {result}
                  </span>
                  <span>
                    {duration} · {formatHHMM(run.startedAt)}
                  </span>
                </div>
              );
            })
          ) : (
            <div className="hud-empty-state">no runs yet</div>
          )}
        </div>

        <div className="hud-deck-footnote">Intents Write to System/Queue — Runner Executes</div>
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">PR Gates</span>
          <span className="hud-suffix">Merge.Link</span>
          <span className="hud-rule" />
        </div>
        {gates.length > 0 ? (
          gates.map((gate) =>
            isGateError(gate) ? (
              <div className="hud-gate-row" key={gate.repo}>
                <div className="hud-gate-top">
                  <span>{gate.repo}</span>
                </div>
                <div className="hud-gate-status">
                  <span className="hud-diamond">◇</span>
                  unavailable
                </div>
              </div>
            ) : (
              <div className="hud-gate-row" key={`${gate.repo}#${gate.number}`}>
                <div className="hud-gate-top">
                  <span>
                    {gate.repo} #{gate.number} {gate.title}
                  </span>
                </div>
                <div className={`hud-gate-status${gate.state === "merge-ready" ? " ready" : ""}`}>
                  <span className="hud-diamond">{gate.state === "merge-ready" ? "◆" : "◇"}</span>
                  {gate.state === "merge-ready"
                    ? "Merge-Ready"
                    : gate.state === "stale"
                      ? "Stale · Sha Mismatch"
                      : `Blocked · Eval ${gate.evals === "missing" ? "Missing" : "Failed"}`}
                </div>
              </div>
            )
          )
        ) : (
          <div className="hud-empty-state">no open PRs</div>
        )}
        <div className="hud-reserved-row">Assistant.Link · Reserved — Sub-Project 4</div>
      </div>
    </section>
  );
}
