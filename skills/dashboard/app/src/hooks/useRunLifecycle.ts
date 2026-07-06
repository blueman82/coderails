"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   The accent tick loop reads performance.now() and writes CSS custom properties on <html>
   every ~50ms while a run is active — a genuinely imperative, time-driven side effect with no
   pure-render equivalent, same class of exception as Scene.tsx's WebGL probe. */

import { useEffect, useRef, useState } from "react";
import { accentAt, hslToRgb, expectedDurationMs, progressFraction, ACCENT_IDLE, type AccentHsl } from "@/lib/runHue";
import type { RunRecord } from "@/lib/runlog";

export interface ActiveRun {
  runId: string;
  button: string;
  startedAt: number;
  expectedMs: number;
}

// Derives the set of in-flight runs from the SSE-fed runs slice: any record with no `endedAt` is
// still running (readRuns already folds each runId down to its newest line, so a finished run's
// start-line never lingers here once its finish-line has arrived).
export function deriveActiveRuns(runs: RunRecord[]): ActiveRun[] {
  return runs
    .filter((r) => r.endedAt === undefined)
    .map((r) => ({
      runId: r.runId,
      button: r.button,
      startedAt: r.startedAt,
      expectedMs: expectedDurationMs(runs, r.button),
    }));
}

// Fraction of the single furthest-along active run, matching the mockup's currentSphereFraction()
// (max across concurrent runs, not an average — so several short runs don't dilute the ramp).
export function furthestProgressFraction(active: ActiveRun[], nowMs: number): number {
  let max = 0;
  for (const run of active) {
    const frac = progressFraction(nowMs - run.startedAt, run.expectedMs);
    if (frac > max) max = frac;
  }
  return max;
}

export interface RunLifecycleState {
  active: ActiveRun[];
  accent: AccentHsl;
  boost: number; // eased 0..1 driver for sphere motion intensity, mirrors accent progress
}

const TICK_MS = 50;
const EASE_IN_RATE = 6; // per second, matches the mockup's tickAccent()
const EASE_OUT_SECONDS = 1.5;

// Drives the CSS custom properties (--accent-h/-s/-l on <html>) and returns the same eased value
// each tick so the sphere (via NetworkSphere's runBoost prop) can tint/boost in lockstep — one
// tick source for both render paths, per the mockup's single tickAccent() driving both.
export function useRunLifecycle(runs: RunRecord[]): RunLifecycleState {
  const [state, setState] = useState<RunLifecycleState>({ active: [], accent: ACCENT_IDLE, boost: 0 });
  const easeRef = useRef(0);
  const lastTickRef = useRef<number | null>(null);
  const runsRef = useRef(runs);

  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);

  useEffect(() => {
    const id = setInterval(() => {
      const now = performance.now();
      const active = deriveActiveRuns(runsRef.current);
      const target = furthestProgressFraction(active, Date.now());

      const last = lastTickRef.current ?? now;
      const dt = Math.min(0.1, (now - last) / 1000);
      lastTickRef.current = now;

      const rate = target > easeRef.current ? EASE_IN_RATE : 1 / EASE_OUT_SECONDS;
      easeRef.current += (target - easeRef.current) * Math.min(1, dt * rate);
      if (Math.abs(easeRef.current) < 0.001) easeRef.current = 0;

      const accent = accentAt(easeRef.current);
      const root = document.documentElement;
      root.style.setProperty("--accent-h", accent.h.toFixed(1));
      root.style.setProperty("--accent-s", accent.s.toFixed(1) + "%");
      root.style.setProperty("--accent-l", accent.l.toFixed(1) + "%");

      setState({ active, accent, boost: easeRef.current });
    }, TICK_MS);

    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}

export { hslToRgb };
