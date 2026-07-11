# Dashboard right-rail UX design — six findings

## Goal

Fix six confirmed UX/IA issues on the coderails observability dashboard's right-hand rail
(Command Deck buttons + Run Output panel + PR Gates), identified via critique and re-confirmed
against current source this session. Separate from the already-fixed ask-output data-extraction
bug (merged, `head_sha 1005d6bc`).

Each finding below ships as its own independent PR — same two components and one shared
stylesheet, but decoupled scope so any one can be reviewed, merged, or dropped without blocking
the others.

## Source files

- `skills/dashboard/app/src/components/RailRight.tsx` — Command Deck button grid, active-run
  list, finished-run history, mounts `OutputViewerPanel` and the PR Gates block.
- `skills/dashboard/app/src/components/OutputViewerPanel.tsx` — Run Output panel: run-history
  picker (all runs, clickable) + settled/live output viewer.
- `skills/dashboard/app/src/styles/hud.css` — all styling; dark theme, monospace, hairline rules,
  rose accent (`--rose: hsl(350 45% 72%)`), no existing card/box chrome anywhere.

## Findings and treatments

### 1. Panel separation

**Problem (verified against source).** `.hud-block` has only `margin-bottom: 30px` — no border,
background, or divider differentiates Command Deck, Run Output, and PR Gates. They read as one
undifferentiated scroll.

**Treatment.** Add a hairline border + `rose-dim` left accent spine and a subtle background wash
to `.hud-block`:

```css
.hud-block {
  border: 1px solid var(--hairline);
  background: rgba(255, 255, 255, 0.02);
  padding: 14px 14px 12px;
  margin-bottom: 14px;
  position: relative;
}
.hud-block::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 2px;
  background: var(--rose-dim);
}
```

CSS-only. No JSX or state changes.

### 2. Input affordance

**Problem (verified).** `.hud-cmd-input` is a bare 1px underline (`border: none; border-bottom: 1px
solid var(--hairline)`), nearly invisible against the dark background. Buttons that accept input
(`inputAllowed: true`) look identical to ones that don't until the user actually clicks and an
input field silently appears.

**Treatment.** Boxed input field (border + background wash) replacing the underline, plus an "arg"
tag on buttons that accept input so the affordance is visible before any click:

```css
.hud-cmd-input {
  border: 1px solid var(--hairline);
  background: rgba(255, 255, 255, 0.03);
  padding: 3px 7px;
}
.hud-cmd .tag {
  font-size: 7.5px;
  letter-spacing: 0.14em;
  color: var(--rose-dim);
  text-transform: uppercase;
  margin-left: 4px;
}
```

JSX: in `RailRight.tsx`, conditionally render `<span className="tag">arg</span>` next to
`btn.label` when `btn.inputAllowed` is true. No new state — `inputAllowed` is already on
`DeckButtonDef`.

### 3. Label wrapping

**Problem (verified).** `.hud-cmd-grid` is `grid-template-columns: 1fr 1fr`. `.hud-label` has no
truncation/nowrap/ellipsis rule. Long button labels wrap to a second line, growing that grid cell
taller than its row neighbor and breaking row alignment.

**Treatment.** Truncate with ellipsis, not wrap; add a native `title` tooltip for the full label on
hover:

```css
.hud-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: inline-block;
  max-width: 100px;
}
```

JSX: add `title={btn.label}` to the `<button>` in `RailRight.tsx`. CSS + one JSX attribute, no new
state.

### 4. Run-history structure

**Problem (verified).** Finished runs render as flat `.hud-run-row` lines with a uniform dim `·`
glyph regardless of outcome — success and failure look identical. Two separate implementations
share this problem: `RailRight.tsx`'s static finished-runs list (non-interactive) and
`OutputViewerPanel.tsx`'s clickable all-runs list (run picker for the output viewer).

**Treatment.** Replace the uniform glyph with a filled/hollow status glyph (◆ success / ◇ failure),
matching the glyph language PR Gates already uses for `merge-ready`/other states:

```css
.hud-run-row .status-ok { color: var(--rose); }
.hud-run-row .status-fail { color: var(--grey-dim); }
```

JSX: in both `RailRight.tsx` and `OutputViewerPanel.tsx`, derive the glyph from the run's outcome.
`runResultLabel(run)` (in `useDashboardState.ts`) already returns a discriminated
`"PASS" | "FAIL" | "RUNNING"` — no extension needed, map `"PASS"` to `.status-ok` (◆) and
`"FAIL"` to `.status-fail` (◇) directly. Applied to both implementations identically so they stay
visually consistent. Minor JSX logic change; no new component state.

Day-grouping ("Today" / "Yesterday" headers) shown in the mockup is a nice-to-have raised during
design exploration but is NOT part of this PR's scope — it would require a date-derivation helper
neither component has today. Flagged here so it isn't silently lost, but deferred to a future
finding if wanted.

### 5. Raw-output formatting (output-viewer context)

**Problem (verified).** `OutputViewerPanel.tsx` renders `<pre className="hud-output-viewer">
{output}</pre>` — the extracted result text (already fixed to be clean text, not raw stream-json,
by the prior merged bugfix) has no header identifying which run produced it. A user can't tell at
a glance whether they're looking at the run they just triggered.

**Treatment.** Attach a header bar above the `<pre>` block showing command name, outcome, and
timestamp, reading as one unit with the output beneath it:

```css
.hud-output-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border: 1px solid var(--hairline);
  border-bottom: none;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.04);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.hud-output-viewer.attached { border-top: none; }
```

JSX: `OutputViewerPanel.tsx` already has `selectedRun` in scope (used to derive `isLive` and
`output`) — render the header from `selectedRun.button`, `runResultLabel(selectedRun)`,
`formatDuration`, and `formatHHMM`, all already imported/available in the file. No new state, no
new data fetch.

Markdown rendering of the output text itself (mentioned in the original finding) is explicitly
**out of scope** for this PR — the header-bar fix addresses "which run is this," not "is this text
formatted." Markdown/ANSI rendering would need a new dependency and its own design pass; flagged
as a follow-up, not silently dropped.

### 6. Button-state differentiation

**Problem (verified).** `.hud-cmd.running` (pulsing bullet) and `.hud-cmd.shake` (reject animation)
already exist and work. The gap: `ButtonUiState.error` renders as a separate `.hud-cmd-error` div
below the button, not a class on the button itself — and there's no "just completed successfully"
state at all. A finished run's button reverts silently to idle with zero visual acknowledgment.

**Treatment.** Transient `.hud-cmd.completed` / `.hud-cmd.failed` classes on the bullet, auto-
clearing after ~1.5s via the same effect lifecycle already used for the `queued` flag:

```css
@keyframes hud-complete-flash {
  0% { background: hsl(120 90% 55%); box-shadow: 0 0 12px hsl(120 90% 55%); }
  100% { background: var(--rose); box-shadow: 0 0 5px var(--rose); }
}
@keyframes hud-fail-flash {
  0%, 50% { background: var(--rose); box-shadow: 0 0 20px var(--rose); }
  100% { background: var(--rose); box-shadow: 0 0 5px var(--rose); }
}
.hud-cmd.completed .hud-bullet { animation: hud-complete-flash 1.5s ease forwards; }
.hud-cmd.failed .hud-bullet { animation: hud-fail-flash 1.5s ease forwards; }
```

**This is the only finding requiring new component state.** `ButtonUiState` in `RailRight.tsx`
gains a `lastOutcome: "completed" | "failed" | null` field. Set it when the `runs` SSE effect
(the same one that clears `queued`, lines ~114-128) observes a previously-active run for this
button transition to `endedAt !== undefined`; derive completed/failed from the run's outcome.
Clear it via a `setTimeout` after 1.5s, mirroring the `shake` timeout pattern already in the file
(`triggerShake`, lines 72-75).

Because this is the only finding touching component state, it carries a different risk/test
profile than findings 1–5 (pure CSS + read-only JSX) and needs its own test coverage for the
auto-clear timing (verify the class is applied, then verify it clears after the timeout without a
stale timer leaking across re-renders/unmounts).

## Non-goals

- Day-grouping in run-history (deferred, noted under finding 4)
- Markdown/ANSI rendering of raw output text (deferred, noted under finding 5)
- Two bonus findings surfaced during design exploration but never in original scope — deck-status
  legibility (Command Deck's status line readability) and gate-scannability (PR Gates
  merge-ready visual weight). Explicitly excluded from this spec per user decision; may become
  their own future finding set, not silently folded in here.

## Testing approach

Findings 1, 2, 3, 5: CSS-only or read-only JSX derived from existing data — verify by inspection
(visual diff against the mockups) and a smoke render, no new test surface.

Finding 4: JSX logic deriving a glyph from run outcome — unit-testable if `runResultLabel` (or an
outcome-boolean derived from it) is a pure function, matching the existing pattern for
`selectDefaultRunId` in `OutputViewerPanel.tsx` (already unit-tested as a pure extraction).

Finding 6: the only finding with new state — needs a test verifying (a) the `completed`/`failed`
class is applied when a run transitions to ended, (b) it clears after the timeout, (c) no stale
timer fires after a component re-render or the button is clicked again mid-flash. Follow
`coderails:test-driven-development` for this PR specifically (write the failing test first).

## Scope note

Per the CLAUDE.md-mandated `coderails:brainstorming` gate, this doc is presented for review before
any implementation. Once approved, `coderails:writing-plans` produces the per-PR implementation
plan; each of the six findings above becomes its own plan task and its own PR through the normal
`coderails:workflow` pipeline (prep → code → push → review → merge), run inside this session's
agentic-loop.

**What "autonomous" means here, precisely (per explicit user authorisation this session, which
also produced a same-day edit to `skills/agentic-loop/SKILL.md`):** routine execution — scope
questions, per-PR confirmations, "want me to spawn X" checks — is skipped by default once this
spec is approved. A failing test or verification check does not stop and ask; it retries
(diagnose, fix, re-verify) in a bounded cycle, escalating only if the bound is exhausted. This is
**not** unconditional autonomy: the loop's four hard-stops (verification failure surviving the
retry bound, a disproven premise, a genuinely ambiguous decision outside this spec's scope, or a
destructive/irreversible action not already covered by this spec) still pause and wait for a
human, and a mandatory Phase 13 terminal summary always runs at the end regardless. This spec's
six findings, treatments, and non-goals are the pre-agreed scope that keeps most decisions inside
the envelope and out of "genuinely ambiguous" territory in the first place.
