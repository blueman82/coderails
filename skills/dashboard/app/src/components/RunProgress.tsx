"use client";

import { useEffect, useState } from "react";
import { useDraggableCallout } from "@/hooks/useDraggableCallout";
import { progressFraction } from "@/lib/runHue";
import type { ActiveRun } from "@/hooks/useRunLifecycle";

function formatMinSec(totalMs: number): string {
  const totalSec = Math.floor(totalMs / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export interface RunProgressProps {
  run: ActiveRun;
  stackIndex: number;
  // Set once the run's SSE record shows endedAt — carries the pass/fail outcome for the resolve
  // flash. undefined means still running.
  resolved: { ok: boolean } | undefined;
  onDone: () => void;
}

const RESOLVE_LINGER_MS = 2000;
const FADE_MS = 650;

export function RunProgress({ run, stackIndex, resolved, onDone }: RunProgressProps) {
  const [anchor, setAnchor] = useState({ x: 0, y: 0 });
  const [now, setNow] = useState(() => Date.now());
  const [fadingOut, setFadingOut] = useState(false);

  useEffect(() => {
    function updateAnchor() {
      setAnchor({ x: window.innerWidth * 0.38, y: window.innerHeight * 0.78 });
    }
    updateAnchor();
    window.addEventListener("resize", updateAnchor);
    return () => window.removeEventListener("resize", updateAnchor);
  }, []);

  useEffect(() => {
    if (resolved) return; // stop ticking once resolved — elapsed freezes at 100%
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [resolved]);

  useEffect(() => {
    if (!resolved) return;
    const lingerId = setTimeout(() => setFadingOut(true), RESOLVE_LINGER_MS);
    const doneId = setTimeout(onDone, RESOLVE_LINGER_MS + FADE_MS);
    return () => {
      clearTimeout(lingerId);
      clearTimeout(doneId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);

  const initial = { x: anchor.x - 260, y: anchor.y - 10 + stackIndex * 74 };
  const { boxRef, style, dragging, leader, onPointerDown } = useDraggableCallout(anchor, initial);

  const elapsedMs = resolved ? run.expectedMs : now - run.startedAt;
  const frac = resolved ? 1 : progressFraction(elapsedMs, run.expectedMs);

  return (
    <>
      <div
        className="hud-leader"
        style={{ left: leader.left, top: leader.top, width: leader.width, height: leader.height }}
      />
      <div
        ref={boxRef}
        className={`hud-callout hud-progress${dragging ? " dragging" : ""}${resolved ? " flash" : ""}${fadingOut ? " fade-out" : ""}`}
        style={{ left: style.left, top: style.top }}
        onPointerDown={onPointerDown}
      >
        <div className="hud-callout-top">
          <span className="hud-diamond">◆</span>
          <span className="hud-label">{run.button.toUpperCase()}</span>
        </div>
        <div className="hud-progress-status">
          <span className="hud-progress-elapsed">{formatMinSec(elapsedMs)}</span>
          {" · "}
          {resolved ? (resolved.ok ? "pass ✓" : "needs review ⚠") : "working"}
        </div>
        <div className="hud-progress-bar-track">
          <div className="hud-progress-bar-fill" style={{ width: `${(frac * 100).toFixed(1)}%` }} />
        </div>
      </div>
    </>
  );
}
