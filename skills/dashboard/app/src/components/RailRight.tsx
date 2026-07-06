"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   `queued` is a genuinely stateful optimistic flag bridging the gap between a click and the
   first SSE 'runs' frame confirming it — it must persist across renders independent of the
   current `runs` prop, then be cleared once that prop confirms the run is no longer relevant.
   No pure-render derivation replaces this; same class of exception as this file's siblings. */

import { useEffect, useState } from "react";
import type { PermissionProfile } from "@/lib/config";
import { useDashboardContext } from "@/components/DashboardProvider";
import { useRunLifecycle } from "@/hooks/useRunLifecycle";
import { formatDuration, formatHHMM, runResultLabel, isGateError } from "@/hooks/useDashboardState";

export interface DeckButtonDef {
  name: string;
  label: string;
  profile: PermissionProfile;
  inputAllowed: boolean;
}

export interface RailRightProps {
  token: string;
  buttons: DeckButtonDef[];
}

interface ButtonUiState {
  inputValue: string;
  error: string | null;
  shake: boolean;
  // Optimistic "queued" flag: set immediately on click, cleared as soon as the SSE `runs` slice
  // confirms the run is active (or the POST itself fails) — bridges the gap between click and
  // the first SSE 'runs' frame, per Task 9d's optimistic-feedback instruction.
  queued: boolean;
}

const EMPTY_UI_STATE: ButtonUiState = { inputValue: "", error: null, shake: false, queued: false };

async function postRun(token: string, button: string, input: string | undefined): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, button, ...(input !== undefined ? { input } : {}) }),
    });
    if (res.ok) return { ok: true };
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    return { ok: false, error: body.error ?? `request failed (${res.status})` };
  } catch {
    return { ok: false, error: "network error" };
  }
}

export function RailRight({ token, buttons }: RailRightProps) {
  const { snapshot } = useDashboardContext();
  const { runs, gates } = snapshot;
  const { active } = useRunLifecycle(runs);
  const [uiState, setUiState] = useState<Record<string, ButtonUiState>>({});

  const activeByButton = new Set(active.map((r) => r.button));
  const activeCount = active.length;

  function getUi(name: string): ButtonUiState {
    return uiState[name] ?? EMPTY_UI_STATE;
  }

  function patchUi(name: string, patch: Partial<ButtonUiState>) {
    setUiState((prev) => ({ ...prev, [name]: { ...(prev[name] ?? EMPTY_UI_STATE), ...patch } }));
  }

  function triggerShake(name: string) {
    patchUi(name, { shake: true });
    setTimeout(() => patchUi(name, { shake: false }), 350);
  }

  async function handleClick(btn: DeckButtonDef) {
    const isRunning = activeByButton.has(btn.name) || getUi(btn.name).queued;
    if (isRunning) {
      triggerShake(btn.name);
      return;
    }

    const ui = getUi(btn.name);
    const input = btn.inputAllowed && ui.inputValue.trim() !== "" ? ui.inputValue.trim() : undefined;
    if (input !== undefined && input.startsWith("-")) {
      patchUi(btn.name, { error: "input can't start with '-'" });
      triggerShake(btn.name);
      return;
    }

    patchUi(btn.name, { queued: true, error: null });
    const result = await postRun(token, btn.name, input);
    if (!result.ok) {
      patchUi(btn.name, { queued: false, error: result.error });
      triggerShake(btn.name);
      return;
    }
    // Leave `queued` true — it's cleared below once the SSE runs slice shows this button active,
    // so the deck never flickers back to idle between the 200 response and the next SSE frame.
  }

  // Clears the local optimistic `queued` flag once `runs` (the single source of truth this
  // effect is keyed on) shows the button either still running or fully finished. Deliberately
  // does NOT consult `activeByButton`/`active` here: those come from useRunLifecycle's own
  // internally-ticking setInterval, which can lag the `runs` prop by up to one tick (~50ms) —
  // mixing that lagging value into an effect keyed only on `[runs]` let `queued` get stuck
  // permanently true if the effect's one and only post-finish invocation happened to read
  // `active` a tick before it had caught up (confirmed empirically: `runs` showed every record
  // finished, `activeByButton` was reported empty by the surrounding render, yet the effect's own
  // read of `activeByButton.has(name)` came back true on that invocation, and since `runs` never
  // changed again afterward, the effect never got a chance to re-evaluate and correct it).
  // `runs` alone is synchronously consistent with itself, so it's the only signal this needs.
  useEffect(() => {
    setUiState((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const [name, ui] of Object.entries(prev)) {
        if (!ui.queued) continue;
        const stillRelevant = runs.some((r) => r.button === name && r.endedAt === undefined);
        if (!stillRelevant) {
          next[name] = { ...ui, queued: false };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [runs]);

  function isButtonBusy(name: string): boolean {
    return activeByButton.has(name) || getUi(name).queued;
  }

  const runningNames = buttons.filter((b) => isButtonBusy(b.name)).map((b) => b.label);
  const engagedCount = runningNames.length;
  const queuedCount = buttons.filter((b) => getUi(b.name).queued && !activeByButton.has(b.name)).length;

  return (
    <section className="hud-rail hud-rail-right hud-intro-rail-right">
      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">Command Deck</span>
          <span className="hud-rule" />
          <span className="hud-deck-status">
            {engagedCount > 0 ? "Engaged" : "Idle"} · {activeCount}/{buttons.length || 4} Active · 0 Queued
          </span>
        </div>

        <div className="hud-active-cmd-list">
          {runningNames.map((label) => (
            <div className="hud-active-cmd-row" key={label}>
              ▸ {label.toUpperCase()}
            </div>
          ))}
        </div>

        <div className="hud-cmd-grid">
          {buttons.map((btn) => {
            const ui = getUi(btn.name);
            const busy = isButtonBusy(btn.name);
            return (
              <div key={btn.name}>
                <button
                  className={`hud-cmd${busy ? " running" : ""}${ui.shake ? " shake" : ""}`}
                  type="button"
                  onClick={() => void handleClick(btn)}
                >
                  <span className="hud-bullet" />
                  <span className="hud-label">{busy ? "Running…" : btn.label}</span>
                </button>
                {btn.inputAllowed && !busy && (
                  <input
                    className="hud-cmd-input"
                    type="text"
                    placeholder="input…"
                    value={ui.inputValue}
                    onChange={(e) => patchUi(btn.name, { inputValue: e.target.value, error: null })}
                  />
                )}
                {ui.error && <div className="hud-cmd-error">{ui.error}</div>}
              </div>
            );
          })}
        </div>

        <div className="hud-run-history">
          {runs.length > 0 ? (
            runs
              .filter((r) => r.endedAt !== undefined)
              .map((run) => {
                const result = runResultLabel(run);
                const duration = run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…";
                return (
                  <div className="hud-run-row" key={run.runId}>
                    <span>
                      <span className="hud-glyph">·</span>
                      {run.button.toUpperCase()} · {result}
                    </span>
                    <span>
                      {duration} · {formatHHMM(run.startedAt)}
                    </span>
                  </div>
                );
              })
          ) : (
            <div className="hud-empty-state">no runs yet</div>
          )}
        </div>

        <div className="hud-deck-footnote">Intents Write to System/Queue — Runner Executes</div>
      </div>

      <div className="hud-block">
        <div className="hud-sec-head">
          <span className="hud-title">PR Gates</span>
          <span className="hud-suffix">Merge.Link</span>
          <span className="hud-rule" />
        </div>
        {gates.length > 0 ? (
          gates.map((gate) =>
            isGateError(gate) ? (
              <div className="hud-gate-row" key={gate.repo}>
                <div className="hud-gate-top">
                  <span>{gate.repo}</span>
                </div>
                <div className="hud-gate-status">
                  <span className="hud-diamond">◇</span>
                  unavailable
                </div>
              </div>
            ) : (
              <div className="hud-gate-row" key={`${gate.repo}#${gate.number}`}>
                <div className="hud-gate-top">
                  <span>
                    {gate.repo} #{gate.number} {gate.title}
                  </span>
                </div>
                <div className={`hud-gate-status${gate.state === "merge-ready" ? " ready" : ""}`}>
                  <span className="hud-diamond">{gate.state === "merge-ready" ? "◆" : "◇"}</span>
                  {gate.state === "merge-ready"
                    ? "Merge-Ready"
                    : gate.state === "stale"
                      ? "Stale · Sha Mismatch"
                      : `Blocked · Eval ${gate.evals === "missing" ? "Missing" : "Failed"}`}
                </div>
              </div>
            )
          )
        ) : (
          <div className="hud-empty-state">no open PRs</div>
        )}
        <div className="hud-reserved-row">Assistant.Link · Reserved — Sub-Project 4</div>
      </div>
    </section>
  );
}
