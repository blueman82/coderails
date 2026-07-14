"use client";

import { Sparkline } from "./Sparkline";
import { useDashboardContext } from "@/components/DashboardProvider";
import { liveLoops, stalledLoops, formatRelativeAge } from "@/hooks/useDashboardState";
import type { HealthTile } from "@/lib/collect/health";
import type { LoopInfo, LoopUnit } from "@/lib/collect/sessions";

// Distinct glyph per unit status — all three union states must read differently
// at a glance (done / in-flight / pending).
const UNIT_GLYPH: Record<LoopUnit["status"], string> = {
  done: "☑",
  "in-flight": "◆",
  pending: "·",
};

function LoopCard({ loop }: { loop: LoopInfo }) {
  return (
    <div className="hud-loop-card" data-testid="loop-card">
      <div className="hud-loop-card-head">
        <span className="hud-loop-title">{loop.title}</span>
        <span className="hud-loop-count">
          {loop.workUnitsDone}/{loop.workUnitsTotal}
        </span>
      </div>
      {loop.units.map((unit) => (
        <div className={`hud-directive-item${unit.status === "done" ? " done" : ""}`} key={unit.key}>
          <span className="hud-box">{UNIT_GLYPH[unit.status]}</span>
          <span className="hud-unit-body">
            <span className="hud-unit-head">
              <span className="hud-unit-key">{unit.key}</span>
              {unit.pr !== undefined && <span className="hud-pr-chip">PR #{unit.pr}</span>}
            </span>
            {unit.description && (
              <span className="hud-unit-desc" title={unit.description}>
                {unit.description}
              </span>
            )}
          </span>
        </div>
      ))}
      {loop.decisions.map((decision, i) => (
        <div className="hud-decision-item" key={`${i}-${decision}`}>
          {decision}
        </div>
      ))}
      <div className="hud-directive-footer">Loop Evals: {loop.evalsFrozen ? "Frozen ✓" : "Not Frozen"}</div>
    </div>
  );
}

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
  const now = Date.now();
  const live = liveLoops(loops, now);
  const stalled = stalledLoops(loops, now);

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
            {loop.units.map((unit) => (
              <div className={`hud-directive-item${unit.status === "done" ? " done" : ""}`} key={unit.key}>
                <span className="hud-box">{unit.status === "done" ? "☑" : "☐"}</span>
                <span>{unit.key}</span>
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

    </section>
  );
}
