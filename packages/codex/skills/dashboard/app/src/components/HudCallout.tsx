"use client";

import { useEffect, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { isGateError } from "@/hooks/useDashboardState";
import { useDraggableCallout } from "@/hooks/useDraggableCallout";

// Merge-ready HUD callout: shows the first merge-ready gate, positioned near the sphere per the
// mockup's sphereAnchorPoint(0.62, 0.22), draggable with a leader line, dismissible with ×.
// Dismissal is per-gate (keyed by repo#number) so a newly merge-ready PR re-surfaces the callout
// even if the user dismissed an earlier one.
export function HudCallout() {
  const { snapshot } = useDashboardContext();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [anchor, setAnchor] = useState({ x: 0, y: 0 });

  useEffect(() => {
    function updateAnchor() {
      setAnchor({ x: window.innerWidth * 0.62, y: window.innerHeight * 0.22 });
    }
    updateAnchor();
    window.addEventListener("resize", updateAnchor);
    return () => window.removeEventListener("resize", updateAnchor);
  }, []);

  const readyGate = snapshot.gates.find((g) => !isGateError(g) && g.state === "merge-ready");
  const gateKey = readyGate && !isGateError(readyGate) ? `${readyGate.repo}#${readyGate.number}` : null;

  const { boxRef, style, dragging, leader, onPointerDown } = useDraggableCallout(anchor, {
    x: anchor.x + 70,
    y: anchor.y - 20,
  });

  if (!readyGate || isGateError(readyGate) || gateKey === dismissed) return null;

  return (
    <>
      <div
        className="hud-leader"
        style={{ left: leader.left, top: leader.top, width: leader.width, height: leader.height }}
      />
      <div
        ref={boxRef}
        className={`hud-callout dismissable${dragging ? " dragging" : ""}`}
        style={{ left: style.left, top: style.top }}
        onPointerDown={onPointerDown}
      >
        <div className="hud-callout-top">
          <span className="hud-diamond">◆</span>
          <span className="hud-label">Merge-Ready</span>
          <button
            className="hud-callout-close"
            type="button"
            aria-label="Dismiss"
            data-callout-close
            onClick={() => setDismissed(gateKey)}
          >
            ×
          </button>
        </div>
        <div className="hud-callout-sub">
          {readyGate.repo} #{readyGate.number} · {readyGate.headSha.slice(0, 7)}
        </div>
      </div>
    </>
  );
}
