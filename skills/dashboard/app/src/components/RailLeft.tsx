"use client";

import { Sparkline } from "./Sparkline";
import { useDashboardContext } from "@/components/DashboardProvider";
import { selectActiveLoop } from "@/hooks/useDashboardState";
import type { HealthTile } from "@/lib/collect/health";

// Static decoration only — no history source exists yet to derive a real
// trend from, so every KPI reuses the same placeholder sparkline shape
// (see Task 9b brief: "do NOT invent one").
const PLACEHOLDER_SPARK = [
  0.3, 0.4, 0.35, 0.45, 0.5, 0.42, 0.55, 0.5, 0.6, 0.55, 0.62, 0.58, 0.65, 0.6, 0.7, 0.68, 0.72, 0.7, 0.75, 0.72,
];

const KPI_LABELS: Record<HealthTile["key"], string> = {
  usage5h: "5H Window",
  usageWeek: "Week",
  hooksFired: "Hooks Fired",
  lintFindings: "Lint Findings",
};

function findTile(health: HealthTile[], key: HealthTile["key"]): HealthTile | undefined {
  return health.find((t) => t.key === key);
}

export function RailLeft() {
  const { snapshot } = useDashboardContext();
  const { health, loops } = snapshot;

  const kpiKeys: HealthTile["key"][] = ["usage5h", "usageWeek", "hooksFired", "lintFindings"];
  const loop = selectActiveLoop(loops);

  return (
    <section className="hud-rail hud-rail-left hud-intro-rail-left">
      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">System Vitals</span>
          <span className="hud-suffix">Usage.Link</span>
          <span className="hud-rule" />
        </div>
        {kpiKeys.map((key) => {
          const tile = findTile(health, key);
          return (
            <div className="hud-kpi" key={key}>
              <div className="hud-kpi-row">
                <span className="hud-kpi-label">
                  <span className="hud-bullet" />
                  {KPI_LABELS[key]}
                </span>
              </div>
              {tile && tile.value !== null ? (
                <div className="hud-kpi-value">{tile.value}</div>
              ) : (
                <div className="hud-kpi-unavailable">{tile?.note ?? "unavailable"}</div>
              )}
              <Sparkline points={PLACEHOLDER_SPARK} />
            </div>
          );
        })}
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Directives</span>
          <span className="hud-suffix">{loop ? `Loop.${loop.workUnitsTotal}` : "Loop.—"}</span>
          <span className="hud-rule" />
        </div>
        {loop ? (
          <>
            {loop.unitTitles.map((unit) => (
              <div className={`hud-directive-item${unit.done ? " done" : ""}`} key={unit.title}>
                <span className="hud-box">{unit.done ? "☑" : "☐"}</span>
                <span>{unit.title}</span>
              </div>
            ))}
            {loop.decisions.map((decision, i) => (
              <div className="hud-decision-item" key={`${i}-${decision}`}>
                {decision}
              </div>
            ))}
            <div className="hud-directive-footer">
              Loop Evals: {loop.evalsFrozen ? "Frozen ✓" : "Not Frozen"}
            </div>
          </>
        ) : (
          <div className="hud-empty-state">no active loop</div>
        )}
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Documents</span>
          <span className="hud-suffix">Memory.Trail</span>
          <span className="hud-rule" />
        </div>
        {trail.length > 0 ? (
          trail.map((entry) => {
            const parts = entry.displayPath.split("/");
            const bold = parts.pop() ?? entry.displayPath;
            const name = parts.length > 0 ? parts.join("/") + "/" : "";
            return (
              <div className="hud-doc-row" key={entry.path}>
                <span className="hud-doc-name">
                  {name}
                  <b>{bold}</b>
                </span>
                <span className="hud-doc-age">{now ? formatRelativeAge(entry.mtime, now) : ""}</span>
              </div>
            );
          })
        ) : (
          <div className="hud-empty-state">no memory files found</div>
        )}
      </div>

      <div className="hud-transcript-pill">
        <span>Transcript</span>
      </div>
    </section>
  );
}
