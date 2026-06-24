# Spec C2 — declaration-based anti-stall guard

**Date:** 2026-06-24
**Status:** Design approved (brainstorming + planning-sequence complete); pending writing-plans
**Targets:** new `hooks/scripts/loop_stall_guard.sh`, new shared `hooks/scripts/lib/loop_state_common.sh`, refactor `hooks/scripts/loop_state_guard.sh` (C1) to source it, `hooks/hooks.json`, `install.sh`, `skills/agentic-loop/SKILL.md`
**Part of:** the agentic-loop improvement decomposition. Spec C was split into **C1** (make progress.json reliable — DONE, merged #13) and **C2** (this — the anti-stall hook that reads it). Sequence: A (done) → C1 (done) → **C2** → B → D.

---

## Problem

The agentic-loop skill exists because, in long autonomous sessions, the orchestrator
drifts into **unauthorised stalls** — yielding control back to the human inside an
authorised, incomplete loop when no real stop condition has been reached. Each stall
is a manual turn the user has to write to restart the loop, destroying the autonomy
they asked for.

The skill *describes* the discipline (Phase 6, Phase 13, the Stop-conditions section)
but nothing *enforces* it. C1 made `progress.json` reliably present + session-owned;
C2 uses that reliability to mechanically catch a stall: an active, incomplete loop
that tries to stop **without declaring why**.

A prior C1 decision rules out the naive approach: a **text-heuristic** anti-stall
(classifying the model's free-form output to guess "is this a legitimate question or
a stall?") was rejected — it cannot separate a real hard-stop question from an
authorised-question stall. C2 is therefore **declaration-based**: the orchestrator
must emit a structured stop declaration, and the hook checks the declaration's
presence and category — never the prose.

## Goal / success criterion

When an agentic loop is active and incomplete in a session, the orchestrator cannot
stop without a `LOOP-STOP: <category> — <reason>` declaration (category from a fixed
vocabulary) in its stopping turn. Legitimate stops pass by carrying the declaration;
silent stalls block. Non-loop sessions are never affected. Phase 13 can count
declarations by category to measure avoidable stalls.

## Scope boundary (what C2 does and does NOT enforce)

C2 enforces **declaration presence + valid category** only:
- A loop is active + incomplete ⇒ a stopping turn carries a `LOOP-STOP` tag whose
  category is one of the fixed vocabulary.

C2 deliberately does **not** judge whether the declared reason is *legitimate* (a
model could write a bogus `complete`). This is the same honest boundary
`check_verify_loop.sh` documents: it forces a categorised declaration, it cannot
force the declaration to be truthful. The guarantee is **"no silent stall — every
yield inside an active loop carries an explicit, vocab-checked reason,"** not "every
stop was genuinely necessary." The declaration is the auditable seam; Phase 13 turns
it into a metric (see below).

## Design decisions (brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Enforcement strength | block immediately (exit 2) — continue-or-declare | Twin of C1 and check_verify_loop; the human always retains the runtime interrupt (Esc), so a block is discipline, not a trap |
| Scope gate | fire whenever the loop is active (C1's structured detector), **no envelope-class branching** | The skill only loads when the user authorised autonomy, so "loop active" already means "gates waived"; gating again on a model-written `envelope_class` would reintroduce a self-report dependency. The declaration subsumes every legitimate-yield case (diagnostic, narrow-fix, redirect) uniformly |
| Declaration site | a structured tag in the **response text** of the stopping turn | Naturally fresh — tied to *this* stop, no recency machinery; matches `check_verify_loop`, which already reads the last assistant message |
| What is checked | **presence + category from a fixed vocabulary** | Mechanical and non-heuristic; nudges the model toward the skill's stop taxonomy without classifying prose |
| Active window / off-switch | same as C1: active invocation exists AND not `complete`-and-not-rearmed | Shared definition with C1; teardown (`status: complete`) is the single off-switch for both hooks |

## The declaration

The orchestrator ends a legitimate stopping turn with a line:

```
LOOP-STOP: <category> — <reason>
```

`<category>` ∈ the fixed vocabulary **`hard-stop | approval-gate | awaiting-input |
complete`**, which maps onto the skill's existing Stop-conditions section:
- `hard-stop` — the four hard-stop conditions (verification failure, premise
  disproven, ambiguous decision outside the envelope, unauthorised destructive op).
- `approval-gate` — a named risk boundary the envelope flagged for sign-off
  (pause-then-proceed).
- `awaiting-input` — a planned interaction point inside the loop (Phase -1
  improve-prompt ask, Phase 1 plan confirmation). This is the one category beyond
  the skill's existing three; it covers the loop's own "ask once" gates so they are
  not false-positive stalls.
- `complete` — all authorised work done; **declaring `complete` MUST also tear the
  loop down** (`progress.json status: complete`, run Phase 13). See the lifecycle
  coupling below — this is load-bearing, not advisory.

## Design (hardened by planning-sequence)

### Single-source vocabulary — no drift across three places

The vocabulary appears in three places that must never disagree: the guard's regex,
the block message, and SKILL.md. The shared lib defines it **once**:

```bash
LOOP_STOP_VOCAB="hard-stop|approval-gate|awaiting-input|complete"
```

The guard builds both its match regex and its block-message template from that single
variable, so the message can never advertise a category the regex rejects.

### Copy-paste tag template in the block message (the C1 path-deadlock lesson)

When the guard blocks, its message contains the **exact tag template the model should
emit**, built from `LOOP_STOP_VOCAB`:

```
[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.
Continue the loop, OR declare your stop by ending your message with:
  LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>
Declaring `complete` means the loop is done: also set progress.json status to
"complete" and run the Phase 13 self-audit.
```

The model copies the template; it never reconstructs the format. This is the direct
analogue of C1 putting the resolved path in its block message.

### `complete` ⇒ teardown coupling (the quiet correctness bug)

C2's durable off-switch is the active-window check (shared with C1): the loop is over
only when `progress.json status == complete` (and not rearmed). A `LOOP-STOP:
complete` tag in the *text* only satisfies the current turn's gate. If the model
declares `complete` in text but leaves `status: in-progress`, **every later stop
still demands a tag and C1 still treats the loop as active** — a hang that looks like
the hook is stuck. Therefore SKILL.md couples them atomically: *declaring `complete`
is the same action as the Phase 13 teardown that sets `status: complete`.* The block
message states this; the lifecycle section enforces it.

### Loop-active detection + shared lib (DRY refactor of C1)

C2 needs exactly the state C1 already computes: the agentic-loop invocation count
(structured `jq` over the transcript), the resolved `progress.json` path, and the
file's `status` / `session_id` / `completed_marker` / rearmed-ness. Rather than
duplicate it, extract that into a sourced lib:

- **Create** `hooks/scripts/lib/loop_state_common.sh` — exposes `LOOP_STOP_VOCAB`
  plus the loop-active/file-state resolution (invocation count with the
  transcript-flush retry, path via `agentic_loop_path.sh`, status/session/marker
  read, rearmed computation). Pure shell, sourced (not executed).
- **Refactor** `hooks/scripts/loop_state_guard.sh` (C1) to source the lib instead of
  computing inline. This MUST be a behaviour-preserving extraction: C1's existing
  8/8 behavioural suite has to pass unchanged against the refactored guard, as a
  mandatory task gate, with no logic edits folded into the same step.
- **Create** `hooks/scripts/loop_stall_guard.sh` (C2) — sources the lib for the
  active-window decision, then adds the last-message tag check.

### The guard hook — `hooks/scripts/loop_stall_guard.sh` (Stop)

Follows the `check_verify_loop.sh` idiom: read payload from stdin via `jq`, numbered
skip-gates that exit early (cheapest first), block via `exit 2` + stderr, append a
`key=value` line to `$CLAUDE_DISCIPLINE_LOG`, retry the last-message read with backoff
for the flush race.

Gates (first match decides):
1. **No transcript** → allow.
2. **Loop-guard:** `stop_hook_active == true` → allow (never double-fire within a turn).
3. **Not a loop:** no agentic-loop invocation in the transcript → allow.
4. **Loop done:** `progress.json status == complete` and not rearmed → allow (shared
   off-switch with C1).
5. **Declared stop:** the last assistant message contains a line matching
   `^LOOP-STOP:[[:space:]]*(<LOOP_STOP_VOCAB>)\b` → allow.
6. **BLOCK (exit 2):** active, incomplete loop with no valid declaration → emit the
   copy-paste template above.

### Registration — `hooks/hooks.json`

Add `loop_stall_guard.sh` to the existing `Stop` array, **after**
`loop_state_guard.sh` (C1 presence is the more fundamental fix; let it speak first),
`timeout: 15`. Final Stop order: `check_confidence_labels` → `check_verify_loop` →
`loop_state_guard` (C1) → `loop_stall_guard` (C2).

### Lifecycle coupling — `skills/agentic-loop/SKILL.md`

Like C1's stub-first contract, C2 needs the skill to teach the declaration:
- A short **stop-ceremony** note: whenever you stop inside an active loop, end the
  message with a `LOOP-STOP: <category> — <reason>` line, *in the same turn* as the
  confidence-label and DNV requirements Phase 0.5 already imposes (so the model emits
  all the stop-ceremony together and does not thrash one hook while satisfying
  another).
- Map the four categories onto the Stop-conditions section, and state the
  `complete` ⇒ teardown coupling explicitly.

### Phase 13 KPI — categories become the stall metric (Red Team mitigation)

`awaiting-input` is a catch-all the model could rubber-stamp; the honest boundary
can't prevent that. The mitigation is **measurement, not a tighter check**: Phase 13
reports the count of `LOOP-STOP` declarations by category over the loop, and treats
the `awaiting-input` count as a primary **avoidable-stall** signal (alongside the
existing human-turn counters). Rubber-stamping then shows up in the factory's own KPI
instead of hiding behind a valid-looking tag. `progress.json` gains a
`loop_stop_counts` object (`{hard-stop, approval-gate, awaiting-input, complete}`)
the orchestrator increments per declaration; Phase 13 surfaces it.

## Files touched

- **Create** `hooks/scripts/loop_stall_guard.sh` — the C2 guard.
- **Create** `hooks/scripts/lib/loop_state_common.sh` — shared detection + vocab.
- **Modify** `hooks/scripts/loop_state_guard.sh` — refactor to source the lib
  (behaviour-preserving; C1's 8/8 suite must stay green).
- **Modify** `hooks/hooks.json` — register the C2 Stop hook after C1.
- **Modify** `install.sh` — add both new scripts to the explicit chmod list (it is a
  hardcoded list, not a glob; `lib/` scripts are not auto-covered).
- **Modify** `skills/agentic-loop/SKILL.md` — stop-ceremony / LOOP-STOP contract,
  `complete`⇒teardown coupling, Phase 13 category KPI, `loop_stop_counts` schema.

## Planning-sequence findings folded in

- **Multi-hook thrash (premortem, highest risk):** C2 is the 4th Stop hook in a
  system that already self-trips. Mitigations: self-contained copy-paste block
  message; a SKILL.md stop-ceremony that bundles LOOP-STOP with the existing
  label/DNV requirements; honour `stop_hook_active`.
- **`complete` off-switch never engages (premortem, quiet bug):** the
  `complete`⇒teardown coupling, stated in both SKILL.md and the block message.
- **Shared-lib refactor regresses C1 (premortem):** mandatory C1-regression gate —
  the existing 8/8 suite runs unchanged against the refactored guard; pure
  extraction, no logic edits in the same step.
- **Catch-all rubber-stamp (red team):** Phase 13 category KPI makes `awaiting-input`
  measurable rather than a silent escape.
- **Copy-paste template + single-source vocab (pre-parade):** the block message
  carries the exact tag; the vocab is defined once in the lib.
- **`AskUserQuestion`/Stop interaction (open verification):** whether
  `AskUserQuestion` fires the Stop hook at all is a planning-phase verification item
  — if it does not, Phase -1/Phase 1 asks never reach C2 (zero friction); if it does,
  they are tagged `awaiting-input`. The design holds either way.

## Known limitations

- **Honest boundary (same as the existing hooks).** C2 forces a categorised
  declaration; it cannot force the category or reason to be truthful. A model can
  rubber-stamp `awaiting-input` or a bogus `complete`. The guarantee is "no silent
  stall," not "no stall." The Phase 13 KPI is the auditable counter-pressure.
- **Whole-transcript scan cost.** Like C1, the invocation count scans the transcript;
  acceptable within the 15s hook timeout.
- **Multi-hook ceremony.** A stopping turn inside a loop now carries three
  requirements (labels, DNV, LOOP-STOP). The stop-ceremony note keeps them together,
  but the surface for an orchestrator self-block is real and is the main thing to
  watch in the Phase 13 avoidable-stall count.

## Testing

- `bash -n` on both new scripts and the refactored C1 guard (the repo's test gate).
- **C1 regression:** the existing `hooks/scripts/tests/loop_state_guard.test.sh`
  passes unchanged against the refactored guard (8/8) — proves the extraction is
  behaviour-preserving.
- **C2 behavioural:** feed synthetic Stop payloads (stdin JSON with a
  `transcript_path` to a fixture `.jsonl` and a last assistant message) to
  `loop_stall_guard.sh`: assert `exit 0` when no agentic-loop invocation; `exit 0`
  when `status==complete` and not rearmed; `exit 0` when the last message carries a
  valid `LOOP-STOP: <vocab>` tag; `exit 2` when active+incomplete with no tag; `exit
  2` when the tag's category is **outside** the vocab; `exit 0` on `stop_hook_active`.
  Fixtures live under a temp dir, not the repo tree.

## Sequencing

A (clean-migration discipline) — DONE, merged #12.
→ C1 (progress.json lifecycle + presence/ownership guard) — DONE, merged #13.
→ **C2** (this) — declaration-based anti-stall guard reading C1's reliable file.
→ B — slim the skill.
→ D — superpowers construction-discipline seam (sonnet-only).
