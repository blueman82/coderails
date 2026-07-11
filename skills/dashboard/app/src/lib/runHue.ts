// Pure run-lifecycle math: accent-hue sweep, median-duration "expected time" estimate, and
// progress-fraction clamping. Ported from the original owner-approved HTML mockup's
// tickAccent()/accentAt()/hslToRgbHex() so the dashboard's CSS custom properties and the
// sphere's material colours are driven by the same function the approved reference used —
// no drift between the two render paths.
import type { RunRecord } from "./runlog";

export interface AccentHsl {
  h: number;
  s: number;
  l: number;
}

export const ACCENT_IDLE: AccentHsl = { h: 350, s: 45, l: 72 };
const ACCENT_MID: AccentHsl = { h: 290, s: 55, l: 74 }; // violet/magenta, early-run
const ACCENT_END: AccentHsl = { h: 140, s: 45, l: 68 }; // green, late-run

// Two-segment sweep: 0-0.5 rose->violet, 0.5-1 violet->green, matching the mockup's accentAt().
export function accentAt(frac: number): AccentHsl {
  const clamped = Math.min(1, Math.max(0, frac));
  if (clamped <= 0.5) {
    const f1 = clamped / 0.5;
    return {
      h: ACCENT_IDLE.h + (ACCENT_MID.h - ACCENT_IDLE.h) * f1,
      s: ACCENT_IDLE.s + (ACCENT_MID.s - ACCENT_IDLE.s) * f1,
      l: ACCENT_IDLE.l + (ACCENT_MID.l - ACCENT_IDLE.l) * f1,
    };
  }
  const f2 = (clamped - 0.5) / 0.5;
  return {
    h: ACCENT_MID.h + (ACCENT_END.h - ACCENT_MID.h) * f2,
    s: ACCENT_MID.s + (ACCENT_END.s - ACCENT_MID.s) * f2,
    l: ACCENT_MID.l + (ACCENT_END.l - ACCENT_MID.l) * f2,
  };
}

export interface RgbColor {
  r: number;
  g: number;
  b: number;
}

export function hslToRgb(h: number, s: number, l: number): RgbColor {
  const sNorm = s / 100;
  const lNorm = l / 100;
  const c = (1 - Math.abs(2 * lNorm - 1)) * sNorm;
  const hp = h / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let r1 = 0;
  let g1 = 0;
  let b1 = 0;
  if (hp >= 0 && hp < 1) {
    r1 = c;
    g1 = x;
  } else if (hp < 2) {
    r1 = x;
    g1 = c;
  } else if (hp < 3) {
    g1 = c;
    b1 = x;
  } else if (hp < 4) {
    g1 = x;
    b1 = c;
  } else if (hp < 5) {
    r1 = x;
    b1 = c;
  } else {
    r1 = c;
    b1 = x;
  }
  const m = lNorm - c / 2;
  return {
    r: Math.round((r1 + m) * 255),
    g: Math.round((g1 + m) * 255),
    b: Math.round((b1 + m) * 255),
  };
}

const DEFAULT_EXPECTED_MS = 30_000;
const MEDIAN_SAMPLE_SIZE = 5;

// Median duration of that button's last N completed runs (endedAt set), newest-first per
// readRuns's ordering — falls back to DEFAULT_EXPECTED_MS when there's no history yet.
export function expectedDurationMs(runs: RunRecord[], button: string): number {
  const durations = runs
    .filter((r) => r.button === button && r.endedAt !== undefined)
    .slice(0, MEDIAN_SAMPLE_SIZE)
    .map((r) => r.endedAt! - r.startedAt)
    .sort((a, b) => a - b);

  if (durations.length === 0) return DEFAULT_EXPECTED_MS;

  const mid = Math.floor(durations.length / 2);
  return durations.length % 2 === 0 ? (durations[mid - 1] + durations[mid]) / 2 : durations[mid];
}

// Elapsed/expected, clamped to [0, 1] so a run that overruns its estimate doesn't overflow the bar.
export function progressFraction(elapsedMs: number, expectedMs: number): number {
  if (expectedMs <= 0) return 1;
  return Math.min(1, Math.max(0, elapsedMs / expectedMs));
}
