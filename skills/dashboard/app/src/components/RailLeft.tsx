import { Sparkline } from "./Sparkline";

// Static placeholder data — Task 9b replaces each block's contents with live collector output
// (System Vitals from health.ts, Directives from sessions.ts, Documents from memoryTrail.ts).
const KPIS = [
  {
    label: "5H Window",
    delta: "▲ 3.0K /WK",
    value: "38",
    unit: "%",
    spark: [0.2, 0.3, 0.25, 0.4, 0.35, 0.5, 0.42, 0.55, 0.5, 0.6, 0.55, 0.65, 0.6, 0.7, 0.65, 0.75, 0.7, 0.8, 0.75, 0.38],
  },
  {
    label: "Week",
    delta: "▲ 1.2K /WK",
    value: "61",
    unit: "%",
    spark: [0.4, 0.35, 0.45, 0.5, 0.48, 0.55, 0.5, 0.6, 0.58, 0.65, 0.6, 0.7, 0.68, 0.72, 0.7, 0.78, 0.75, 0.8, 0.78, 0.61],
  },
  {
    label: "Hooks Fired",
    delta: "▲ 18 /DAY",
    value: "142",
    unit: "",
    spark: [0.3, 0.4, 0.35, 0.45, 0.5, 0.42, 0.55, 0.5, 0.6, 0.55, 0.62, 0.58, 0.65, 0.6, 0.7, 0.68, 0.72, 0.7, 0.75, 0.72],
  },
  {
    label: "Lint Findings",
    delta: "▼ 2 /WK",
    value: "3",
    unit: "",
    spark: [0.7, 0.65, 0.68, 0.6, 0.55, 0.58, 0.5, 0.45, 0.48, 0.4, 0.35, 0.38, 0.3, 0.32, 0.28, 0.25, 0.22, 0.2, 0.18, 0.15],
  },
];

const DIRECTIVES = [
  { done: true, text: "Wire task-evals schema into loop intake sequence" },
  { done: true, text: "Freeze eval tiers for PR gate board integration" },
  { done: false, text: "Resolve comment-spoofing trust model for eval oracle" },
  { done: false, text: "Wire merge-gate check against frozen eval artifact" },
  { done: false, text: "Add dormant-eval detection to wiki-lint pass" },
  { done: false, text: "Draft skill-eval runner corpus threshold decision" },
  { done: false, text: "Close out task-evals follow-up loop and archive" },
];

const DOCS = [
  { name: "coderails-wiki/architecture/", bold: "task-evals.md", age: "18m" },
  { name: "memory/", bold: "project_task_evals_feature.md", age: "1h" },
  { name: "assistant-agent-wiki/", bold: "log.md", age: "3h" },
  { name: "coderails-wiki/", bold: "index.md", age: "5h" },
];

export function RailLeft() {
  return (
    <section className="hud-rail hud-rail-left">
      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">System Vitals</span>
          <span className="hud-suffix">Usage.Link</span>
          <span className="hud-rule" />
        </div>
        {KPIS.map((kpi) => (
          <div className="hud-kpi" key={kpi.label}>
            <div className="hud-kpi-row">
              <span className="hud-kpi-label">
                <span className="hud-bullet" />
                {kpi.label}
              </span>
              <span className="hud-kpi-delta">{kpi.delta}</span>
            </div>
            <div className="hud-kpi-value">
              {kpi.value}
              {kpi.unit && <span className="hud-unit">{kpi.unit}</span>}
            </div>
            <Sparkline points={kpi.spark} />
          </div>
        ))}
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Directives</span>
          <span className="hud-suffix">Loop.7</span>
          <span className="hud-rule" />
        </div>
        {DIRECTIVES.map((d) => (
          <div className={`hud-directive-item${d.done ? " done" : ""}`} key={d.text}>
            <span className="hud-box">{d.done ? "☑" : "☐"}</span>
            <span>{d.text}</span>
          </div>
        ))}
        <div className="hud-directive-footer">Loop Evals: Frozen ✓</div>
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Documents</span>
          <span className="hud-suffix">Memory.Trail</span>
          <span className="hud-rule" />
        </div>
        {DOCS.map((doc) => (
          <div className="hud-doc-row" key={doc.name + doc.bold}>
            <span className="hud-doc-name">
              {doc.name}
              <b>{doc.bold}</b>
            </span>
            <span className="hud-doc-age">{doc.age}</span>
          </div>
        ))}
      </div>

      <div className="hud-transcript-pill">
        <span>Transcript</span>
      </div>
    </section>
  );
}
