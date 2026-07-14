"use client";

import { useDashboardContext } from "@/components/DashboardProvider";
import { selectActiveLoop } from "@/hooks/useDashboardState";

export function BottomHero() {
  const { snapshot } = useDashboardContext();
  const loop = selectActiveLoop(snapshot.loops);
  const nextUnit = loop?.units.find((u) => u.status !== "done");

  return (
    <div className="hud-bottom-centre hud-intro-bottom">
      {loop ? (
        <>
          <div className="hud-bc-label hud-bc-loop-name">Primary Directive · {loop.title}</div>
          <div className="hud-bc-units">
            <span className="hud-bc-value">
              {loop.workUnitsDone}/{loop.workUnitsTotal}
            </span>
            <span className="hud-bc-units-label">Units</span>
          </div>
          <div className="hud-bc-ticker">{nextUnit ? `Next: ${nextUnit.key} …` : "All units complete"}</div>
        </>
      ) : (
        <div className="hud-bc-label hud-empty-state">Primary Directive · no active loop</div>
      )}
    </div>
  );
}
