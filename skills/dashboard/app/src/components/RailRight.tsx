// Static placeholder data — Task 9b binds Command Deck to the runner/argv module and PR Gates
// to prGates.ts; Task 9d wires the run/click lifecycle onto these buttons.
const COMMANDS = [
  { label: "Wiki Lint" },
  { label: "Sync Docs" },
  { label: "AM Report" },
  { label: "Deep Research" },
  { label: "PR Gates" },
  { label: "WK Review" },
];

const RUN_HISTORY = [
  { name: "WIKI-LINT", result: "PASS", meta: "42S · 09:14" },
  { name: "AM-REPORT", result: "PASS", meta: "3M10S · 07:00" },
  { name: "SYNC-DOCS", result: "FAIL", meta: "12S · YDAY" },
];

const GATES = [
  { title: "coderails #6 Dashboard Skill", ready: true, status: "Merge-Ready" },
  { title: "coderails #7 Routines", ready: false, status: "Blocked · Eval Missing" },
  { title: "liftlog #14", ready: false, status: "Stale · Sha Mismatch" },
];

export function RailRight() {
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
          {RUN_HISTORY.map((run) => (
            <div className="hud-run-row" key={run.name}>
              <span>
                <span className="hud-glyph">·</span>
                {run.name} · {run.result}
              </span>
              <span>{run.meta}</span>
            </div>
          ))}
        </div>

        <div className="hud-deck-footnote">Intents Write to System/Queue — Runner Executes</div>
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">PR Gates</span>
          <span className="hud-suffix">Merge.Link</span>
          <span className="hud-rule" />
        </div>
        {GATES.map((gate) => (
          <div className="hud-gate-row" key={gate.title}>
            <div className="hud-gate-top">
              <span>{gate.title}</span>
            </div>
            <div className={`hud-gate-status${gate.ready ? " ready" : ""}`}>
              <span className="hud-diamond">{gate.ready ? "◆" : "◇"}</span>
              {gate.status}
            </div>
          </div>
        ))}
        <div className="hud-reserved-row">Assistant.Link · Reserved — Sub-Project 4</div>
      </div>
    </section>
  );
}
