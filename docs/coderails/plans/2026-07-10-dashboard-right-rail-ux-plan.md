**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Dashboard right-rail UX — Implementation Plan

**Goal:** Ship the six right-rail UX findings from `docs/coderails/specs/2026-07-10-dashboard-right-rail-ux-design.md`, each as its own independent PR, plus a 7th PR for the already-written agentic-loop skill edit.

**Architecture:** Two React components (`RailRight.tsx`, `OutputViewerPanel.tsx`) and one shared stylesheet (`hud.css`) in `skills/dashboard/app/src/`. Six tasks are CSS-only or CSS + trivial read-only JSX (no new state); one task (button-state) adds component state and needs test coverage. Task 7 is push+review+merge of pre-existing, pre-verified skill-file changes — no new implementation.

## Global Constraints

- Every finding ships as its own PR through `coderails:workflow` (prep → code → push → review → merge) — never bundle two findings into one PR.
- Findings 1, 2, 3, 4, 5: verify by inspection (visual match against the already-approved mockups) + a smoke render. No `coderails:test-driven-development` gate — there is no testable branch/function being added.
- Finding 6: the only task with new component state — build test-first via `coderails:test-driven-development`.
- Do not touch the two bonus findings (deck-status legibility, gate-scannability) — explicitly out of scope per the spec's Non-goals section.
- Do not implement day-grouping (finding 4) or markdown/ANSI rendering (finding 5) — explicitly deferred per spec.
- CSS custom properties already exist in `hud.css` (`--hairline`, `--rose`, `--rose-dim`, `--grey-dim`) — reuse them, never hardcode a hex/hsl value that duplicates an existing token.
- **Before each task's `coderails:workflow` `prep` step, confirm the worktree/branch is clean and on latest `main`** (`git status --short` empty, `git fetch origin && git rev-parse HEAD` matches `git rev-parse origin/main`). `/prep`'s `git worktree add <path> -b <branch> ` branches from whatever `HEAD` the invoking shell is at — it does not itself pull latest `main` first, so this precondition is not redundant with `/prep`'s own behavior; skipping it risks a task branching off a stale or already-superseded base.
- **Each task (1–7) freezes its OWN pr-scope `evals.json` via `coderails:task-evals`, before that task's implementation dispatch begins** — not one shared loop-scope eval graded only at Task 8. Confirmed against source this session: `commands/merge.md` / `scripts/merge.sh` verify a SHA-bound `/coderails:post-evals` artifact on every merge, and `commands/workflow.md` Phase 3 step 6 runs `task-evals` → `post-evals` per-PR. A single loop-scope eval cannot satisfy `merge.sh`'s gate for Tasks 1–6's individual merges — each needs its own frozen-before-implementation eval, graded and posted at that task's own end (folded into that task's existing steps, not a separate task).

---

## Task 1: Panel separation — bounded card treatment

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (modify `.hud-block` rule, currently at line ~235-240)

**Interfaces:** None — pure CSS, no props/state/exports change.

**Note — `.hud-block` is a shared, global class, not right-rail-specific.** Confirmed via grep this session: it is also used by `RailLeft.tsx` (3 instances, lines 46/73/96) and `AssistantLinkPanel.tsx` (line 353), not only `RailRight.tsx`/`OutputViewerPanel.tsx`. This task's CSS change therefore affects the ENTIRE dashboard, not just the three right-rail panels named in the finding — this is consistent with the finding's actual intent (panel separation is a general problem) and is the correct, larger blast radius, not an error. Visually confirm both rails, not just the right one.

**Steps:**
- [ ] Read the current `.hud-block` rule in `hud.css` to confirm it is still exactly `margin-bottom: 30px;` / `.hud-block:last-child { margin-bottom: 0; }` (spec's stated baseline — re-verify before editing, do not assume unchanged).
- [ ] Replace/extend `.hud-block` with the spec's treatment: `border: 1px solid var(--hairline); background: rgba(255, 255, 255, 0.02); padding: 14px 14px 12px; margin-bottom: 14px; position: relative;` — keep the existing `margin-bottom: 0` override on `:last-child`.
- [ ] Add `.hud-block::before` per the spec: `content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: var(--rose-dim);`
- [ ] Run the dashboard dev server (`skills/dashboard/app`, `npm run dev` or the project's declared dev command) and visually confirm ALL `.hud-block` instances across BOTH rails (Command Deck, Run Output, PR Gates on the right; the 3 blocks in `RailLeft.tsx`; `AssistantLinkPanel.tsx`) now show a bordered card with a left rose-dim spine, matching `mockups/1-panel-separation.html`'s "Proposed — bounded cards" pane, with no layout breakage on the left rail specifically (it was not part of the original critique, so it must not regress).

**Verify-criteria:** Dev server renders every `.hud-block` instance (both rails) with visible per-block borders + left accent spine; explicit visual check confirms the left rail has no layout regression despite not being part of the original finding.

---

## Task 2: Input affordance — boxed field + arg tag

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (modify `.hud-cmd-input`, add `.hud-cmd .tag`)
- `skills/dashboard/app/src/components/RailRight.tsx` (modify the button JSX at lines 163-170)

**Interfaces:** No new exports. Reads existing `DeckButtonDef.inputAllowed: boolean` (already defined, `RailRight.tsx:16-21`) — no interface change.

**Steps:**
- [ ] In `hud.css`, replace `.hud-cmd-input`'s current underline styling with: `border: 1px solid var(--hairline); background: rgba(255, 255, 255, 0.03); padding: 3px 7px;` (remove the `border-bottom`-only rule; keep any existing `font-family`/`color`/`width` declarations already on the selector — read the current rule first, don't blind-overwrite).
- [ ] Add new rule `.hud-cmd .tag { font-size: 7.5px; letter-spacing: 0.14em; color: var(--rose-dim); text-transform: uppercase; margin-left: 4px; }`.
- [ ] In `RailRight.tsx`, inside the `<span className="hud-label">` block (line 169), add a conditional sibling: `{btn.inputAllowed && !busy && <span className="tag">arg</span>}` immediately after the `hud-label` span, inside the `<button>`.
- [ ] Visually confirm: buttons with `inputAllowed: true` (e.g. Ask, Verify-Q per the mockup) show an "ARG" tag next to their label even before any click; the input field itself now renders with a visible box border matching `mockups/2-input-affordance.html`'s proposed treatment.

**Verify-criteria:** Dev server shows a visible "ARG" tag on input-capable buttons; clicking one reveals a boxed (not underlined) input field.

---

## Task 3: Label wrapping — ellipsis truncation + tooltip

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (modify `.hud-label`)
- `skills/dashboard/app/src/components/RailRight.tsx` (add `title` attribute, line 163-167)

**Interfaces:** None new.

**Note — `.hud-label` is used by two other components beyond `RailRight.tsx`.** Confirmed via grep this session: `RunProgress.tsx:78` (`<span className="hud-label">{run.button.toUpperCase()}</span>`) and `HudCallout.tsx:50` (`<span className="hud-label">Merge-Ready</span>`). Neither is part of this finding's scope, so the new truncation rule must not visibly clip their content — check both render inside a wide-enough container that `max-width: 100px` never actually constrains them (or scope the new declarations to `.hud-cmd .hud-label` instead of bare `.hud-label` if either turns out to sit in a narrow container).

**Steps:**
- [ ] In `hud.css`, add to `.hud-label`: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: inline-block; max-width: 100px;` (read the current `.hud-label` rule first — it may already have `text-transform`/`color`/`font-*` declarations from the parent `.hud-cmd` cascade; add these as new declarations, don't replace the rule wholesale). Prefer scoping to `.hud-cmd .hud-label` over bare `.hud-label` unless confirmed safe for `RunProgress.tsx`/`HudCallout.tsx`'s usage too.
- [ ] In `RailRight.tsx`, add `title={btn.label}` to the `<button>` element (line 163), so the full label is available as a native tooltip regardless of truncation state.
- [ ] Temporarily test with a long label (e.g. rename a button's `label` in the dashboard config to something like "Verify-Merged-PR" in a local/dev config, or use browser devtools to inject a long string into one `.hud-label` span) to visually confirm it truncates with "…" instead of wrapping, and that both grid cells in that row stay the same height. Revert any temporary config change before committing.
- [ ] Visually confirm `RunProgress.tsx` and `HudCallout.tsx`'s `.hud-label` usages are unaffected (no unexpected clipping of "Merge-Ready" or button-name text in those components).

**Verify-criteria:** A long button label truncates with an ellipsis and does not wrap to a second line; hovering shows the full label via native browser tooltip; grid row height stays uniform; `RunProgress.tsx` and `HudCallout.tsx` show no visual regression.

---

## Task 4: Run-history structure — status glyph

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (add `.status-ok`, `.status-fail` under `.hud-run-row`)
- `skills/dashboard/app/src/components/RailRight.tsx` (modify the run-history row render, lines 186-208)
- `skills/dashboard/app/src/components/OutputViewerPanel.tsx` (modify the run-history-picker row render, lines 156-178)

**Interfaces:** Consumes `runResultLabel(run: RunRecord): "PASS" | "FAIL" | "RUNNING"` — already exported from `skills/dashboard/app/src/hooks/useDashboardState.ts` (confirmed present this session via grep; re-confirm the exact export signature is unchanged before use, since both files already import it).

**Steps:**
- [ ] In `hud.css`, add: `.hud-run-row .status-ok { color: var(--rose); } .hud-run-row .status-fail { color: var(--grey-dim); }`.
- [ ] In `RailRight.tsx`'s run-history block (lines 186-208): replace the static `<span className="hud-glyph">·</span>` with a glyph derived from `runResultLabel(run)` — `"PASS"` → `<span className="hud-glyph status-ok">◆</span>`, `"FAIL"` → `<span className="hud-glyph status-fail">◇</span>`. `"RUNNING"` should not occur here since this list is already filtered to `r.endedAt !== undefined` (line 189) — if it does appear, fall back to the existing `·` glyph as a defensive default (do not crash on an unhandled case). Add a one-line comment above this block: `// Glyph-derivation logic duplicated intentionally in OutputViewerPanel.tsx — two real independent run-history implementations exist; keep both mappings in sync if either changes.`
- [ ] In `OutputViewerPanel.tsx`'s run-history-picker block (lines 156-178): apply the identical glyph-derivation logic to its `<span className="hud-glyph">·</span>` (line 169) — same three-way mapping, same defensive `"RUNNING"` fallback (this list is NOT pre-filtered to ended runs, so `"RUNNING"` is a real case here, not defensive-only; use `·` for it). Add the matching cross-reference comment: `// Glyph-derivation logic duplicated intentionally from RailRight.tsx — keep both mappings in sync if either changes.`
- [ ] Visually confirm both lists show ◆ for passed runs and ◇ for failed runs, matching `mockups/3-run-history-structure.html`'s "Proposed" pane (ignore the mockup's day-grouping — explicitly out of scope per Task 4's non-goal).

**Verify-criteria:** Both run-history implementations show filled/hollow glyphs matching run outcome; a live/running run in `OutputViewerPanel.tsx`'s list still shows `·`, not a crash or blank glyph.

---

## Task 5: Output-viewer context — run header bar

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (add `.hud-output-header`, modify `.hud-output-viewer`)
- `skills/dashboard/app/src/components/OutputViewerPanel.tsx` (add header JSX before the `<pre>` block, near line 191)

**Interfaces:** Consumes `selectedRun: RunRecord | undefined` (already computed in-component at line 94), `runResultLabel`, `formatDuration`, `formatHHMM` (already imported, line 5). No new props/exports.

**Steps:**
- [ ] In `hud.css`, add: `.hud-output-header { display: flex; justify-content: space-between; align-items: baseline; border: 1px solid var(--hairline); border-bottom: none; padding: 6px 10px; background: rgba(255, 255, 255, 0.04); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; }` and `.hud-output-viewer.attached { border-top: none; }`.
- [ ] In `OutputViewerPanel.tsx`, immediately before the `<pre className="hud-output-viewer">` block (~line 191), add: when `selectedRun` is defined, render `<div className="hud-output-header"><span>{selectedRun.button.toUpperCase()}</span><span>{runResultLabel(selectedRun)} · {selectedRun.endedAt ? formatDuration(selectedRun.startedAt, selectedRun.endedAt) : "…"} · {formatHHMM(selectedRun.startedAt)}</span></div>`.
- [ ] Add `attached` to the `<pre>` element's className whenever the header is rendered (i.e. whenever `selectedRun` is defined) so the two visually join with no gap: `className={`hud-output-viewer${selectedRun ? " attached" : ""}`}`.
- [ ] Visually confirm the output panel now shows a header bar (command name, outcome, duration, timestamp) directly above the output text, reading as one joined block, matching `mockups/5-output-viewer-context.html`'s "After" pane.

**Verify-criteria:** Selecting any run in the picker shows a header bar above its output identifying which run it is; no header bar when no run is selected (empty state unaffected).

---

## Task 6: Button-state differentiation — transient completed/failed bullet flash

**Files:**
- `skills/dashboard/app/src/styles/hud.css` (add `@keyframes hud-complete-flash`, `@keyframes hud-fail-flash`, `.hud-cmd.completed`, `.hud-cmd.failed`)
- `skills/dashboard/app/src/components/RailRight.tsx` (extend `ButtonUiState`, the `runs` SSE effect at lines 114-128, and the button className at line 164)
- `skills/dashboard/app/src/components/RailRight.test.tsx` (new or extended test file — check whether one already exists for this component before assuming new)

**Interfaces:**
- `ButtonUiState` (currently `RailRight.tsx:28-36`) gains one field: `lastOutcome: "completed" | "failed" | null`.
- `EMPTY_UI_STATE` (line 38) gains `lastOutcome: null`.
- No new exports — this is internal component state, not consumed by any other file.

**This is the only task requiring test-first construction — follow `coderails:test-driven-development`.**

**Test infrastructure gap — confirmed this session, must be resolved before any test-writing step below.** `vitest.config.ts` currently declares `test: { environment: "node" }` and `package.json` has no `@testing-library/react` dependency — there is zero precedent in this codebase for mounting/rendering a React component in a test. This is real setup work, not an assumption to "check":

- [ ] Add `@testing-library/react` (and `@testing-library/jest-dom` if assertions need it) as a dev dependency in `skills/dashboard/app/package.json`.
- [ ] Add a `// @vitest-environment jsdom` docblock comment at the top of the new test file (per-file environment override — avoids changing the global `node` environment other existing tests may depend on) OR confirm with a quick check that switching the global environment to `jsdom` doesn't break any existing test (grep existing `.test.ts`/`.test.tsx` files for `environment: "node"` assumptions first — if none exist, a global `jsdom` switch in `vitest.config.ts` is simpler and preferred).
- [ ] Create `skills/dashboard/app/src/components/RailRight.test.tsx` — confirmed no such file exists yet (grep this session found nothing), so this task creates the first test for this component from scratch, including whatever mock/provider setup `RailRight`'s `useDashboardContext()` and `useRunLifecycle()` hooks require (check `DashboardProvider.tsx` and `useRunLifecycle.ts` for how to supply test fixtures/mocks for these).
- [ ] Write a failing test: given a button whose `runs` entry transitions from `endedAt: undefined` to `endedAt: <timestamp>` with a `"PASS"` outcome, the component applies `.hud-cmd.completed` to that button's `<button>` element. Assert the class is present immediately after the transition.
- [ ] Write a failing test: the same for a `"FAIL"` outcome → `.hud-cmd.failed`.
- [ ] Write a failing test: after 1.5s (use fake timers), the `completed`/`failed` class is removed and the button returns to its plain `hud-cmd` state.
- [ ] Write a failing test: if the button is clicked again (a new run starts) before the 1.5s timeout elapses, the stale timeout does not fire and incorrectly clear a *newer* `queued`/`running` state — i.e. no cross-contamination between one run's outcome-clear timer and the next run's state.
- [ ] Write a failing test: the component unmounts while a `completed`/`failed` clear-timeout is still pending — the timeout must be cleaned up (e.g. via the `useEffect` cleanup function) and must not throw or attempt a state update on an unmounted component.
- [ ] Confirm all five tests fail for the right reason (feature/infra not yet implemented, not a typo/setup error).
- [ ] Implement: add `lastOutcome: "completed" | "failed" | null` to `ButtonUiState` (line 28-36) and to `EMPTY_UI_STATE` (line 38).
- [ ] Extend the `runs` SSE effect (lines 114-128): for each button whose `queued` flag is being cleared because its run just ended (the existing `!stillRelevant` branch), also set `lastOutcome` based on that run's `runResultLabel()` result (`"PASS"` → `"completed"`, `"FAIL"` → `"failed"`), and schedule a `setTimeout` (1.5s) to clear `lastOutcome` back to `null` via `patchUi`, mirroring the existing `triggerShake` timeout pattern (lines 72-75). Store the timeout handle (e.g. in a `useRef<Record<string, ReturnType<typeof setTimeout>>>`) so a new run for the same button can clear any still-pending prior timeout before scheduling its own — this is what the fourth test above verifies. Add a `useEffect` cleanup function that clears all pending timeout handles in the ref on unmount — this is what the fifth (unmount) test above verifies.
- [ ] Add `@keyframes hud-complete-flash` / `@keyframes hud-fail-flash` and `.hud-cmd.completed .hud-bullet` / `.hud-cmd.failed .hud-bullet` to `hud.css`, exactly as specified (spec lines 177-187).
- [ ] Update the button's `className` (line 164) to also include `completed`/`failed` when `ui.lastOutcome` is set: `` `hud-cmd${busy ? " running" : ""}${ui.shake ? " shake" : ""}${ui.lastOutcome ? ` ${ui.lastOutcome}` : ""}` ``.
- [ ] Run all five tests, confirm all pass.
- [ ] Visually confirm in the dev server: triggering a run and watching it complete shows a brief green (success) or intensified rose (failure) bullet flash that clears after ~1.5s, matching `mockups/6-button-state.html`'s "After" pane.

**Verify-criteria:** All five new tests pass; `npm test` (or project test command) is green with no regressions in existing tests; visual confirmation of the flash-then-clear behavior in the dev server.

---

## Task 7: Ship the agentic-loop skill edit (push + review + merge only)

**Files:** None to create/modify — `skills/agentic-loop/SKILL.md` and `skills/agentic-loop/retry-until-green.md` are already written, committed, and test-verified (38/38 hook suites, this session) on the current branch (`worktree-dashboard-ux-rail`).

**Interfaces:** N/A — no code interfaces, this is a documentation/process change.

**Steps:**
- [ ] Confirm no further edits are pending: `git status --short` on this branch should show a clean tree for these two files (verify — do not assume from memory of earlier turns).
- [ ] This task's deliverable is docs/config with no testable code — verify by inspection: re-read the final `skills/agentic-loop/SKILL.md` stop-conditions section and `retry-until-green.md` once more end-to-end for internal consistency (the four hard-stops are still named correctly, the pointer link resolves, no leftover TODO/placeholder).
- [ ] Re-run `hooks/scripts/tests/run_all.sh` one final time immediately before push, to catch any drift introduced by Tasks 1-6's commits landing on the same branch.
- [ ] **Precondition check, stop-and-flag (not silent recovery) if it fails:** run `git log main..HEAD --stat` and confirm the changed-file list contains ONLY `skills/agentic-loop/SKILL.md` and `skills/agentic-loop/retry-until-green.md`. If Tasks 1-6 have already landed commits on this same branch/worktree by the time Task 7 runs, this check will fail — do NOT silently cherry-pick or attempt to split the branch to route around it. Treat a failing precondition here as a genuinely ambiguous decision outside this plan's pre-agreed scope (hard-stop #3 in `agentic-loop/SKILL.md`'s stop conditions) and surface it rather than guessing at a recovery mechanism — the right fix depends on how the other 6 tasks' PRs were actually structured by the time this task runs, which this plan cannot predict in advance.
- [ ] Push and open a PR for just these two files via `coderails:push`.
- [ ] Freeze and post this task's own pr-scope eval via `coderails:task-evals` → `coderails:post-evals`, per the Global Constraints eval-freeze rule.
- [ ] Run `coderails:post-review` after `pr-review-toolkit:review-pr` completes and any findings are addressed.

**Verify-criteria:** PR contains only `skills/agentic-loop/SKILL.md` and `skills/agentic-loop/retry-until-green.md`; `hooks/scripts/tests/run_all.sh` reports 38/38 (or higher, if new tests were added elsewhere) immediately before push.

---

## Task 8 (final): Loop-scope summary

**Files:** None — this is not a merge-gating eval (each of Tasks 1-7 already froze, graded, and posted its own pr-scope eval per the Global Constraints rule, satisfying `merge.sh`'s per-PR gate individually). This task is agentic-loop's own Phase 13 terminal self-audit, not a `coderails:task-evals` invocation.

**Steps:**
- [ ] After Tasks 1-7 are all merged, run agentic-loop's Phase 13 terminal self-audit (per `skills/agentic-loop/SKILL.md`): report `LOOP-STOP` category counts, decisions absorbed, artifacts produced (the 7 merged PRs with their verifying checks), and each task's individual pr-scope eval result — unscored, raw facts, per Phase 13's own framing.

**Verify-criteria:** Phase 13 self-audit is reported; `retro.json` is written per the teardown contract before the loop's `complete` declaration.
