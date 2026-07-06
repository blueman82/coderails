"use client";

import { useDashboardState } from "@/hooks/useDashboardState";

export function BottomHero() {
  const { snapshot } = useDashboardState();
  const loop = snapshot.loops[0];
  const nextUnit = loop?.unitTitles.find((u) => !u.done);

  return (
    <div className="hud-bottom-centre">
      {loop ? (
        <>
          <div className="hud-bc-label">Primary Directive · {loop.slug}</div>
          <div className="hud-bc-units">
            <span className="hud-bc-value">
              {loop.workUnitsDone}/{loop.workUnitsTotal}
            </span>
            <span className="hud-bc-units-label">Units</span>
          </div>
          <div className="hud-bc-ticker">{nextUnit ? `Next: ${nextUnit.title} …` : "All units complete"}</div>
        </>
      ) : (
        <div className="hud-bc-label hud-empty-state">Primary Directive · no active loop</div>
      )}
    </div>
  );
}
