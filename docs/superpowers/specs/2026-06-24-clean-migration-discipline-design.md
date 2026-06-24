# Spec A — Clean-migration discipline

**Date:** 2026-06-24
**Status:** Design approved; pending writing-plans
**Target:** `skills/agentic-loop/SKILL.md` (+ `progress.json` schema documented therein)
**Part of:** a three-spec decomposition of agentic-loop improvements. Sequence: **A → C → B.**

---

## Problem

The agentic-loop skill is calibrated in one direction only. Almost every phase
guards against **over-asking** — stalls, re-asks, holding at removed gates
(Phase 6, Phase 0, Phase 13's KPI). It is blind to the opposite failure:
**silent over-production** — building more than was asked, invisibly, until the
human inspects the artifact.

The concrete instance that triggered this work: during a code migration the loop
defaulted to keeping legacy shims, bridges, and compat paths — reasoning that the
human wanted existing functionality preserved — without ever surfacing that
choice. The result was double work: the migration had to be re-invoked with
explicit instructions to strip the shims, instead of landing clean the first
time.

Root cause: Phase 0 classifies the authorisation envelope by **autonomy**
(full-autonomous / narrow-fix / diagnostic / ambiguous) but never by
**disposition** — clean-break vs preserve-compat. For a migration that is the
load-bearing question, and the model's untold default leans conservative
("don't break things" feels safe). The skill never forces the fork to be
resolved, so the model fills it silently with the cautious answer.

## Goal / success criterion

Migrations land clean the first time. The user never has to re-invoke the loop to
remove shims the loop itself inserted without asking. Where compat genuinely must
be kept, it is an explicit, justified, time-bounded decision — not a silent
default.

## Design decisions (resolved during brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Default on unspecified disposition | **Ask once up front** | The fork is cheap to ask and expensive to get wrong (doubled work). One question is insurance, not a recurring stall. Modelled on Phase 2.5 design-fork resolution. |
| Trigger for the question | **Replacement-shaped work**, tightened to "an *existing* code path is being *retired*" (a named thing-being-replaced) | Catches the actual shim risk regardless of wording, without over-firing on every edit that wraps old code. |
| Enforcement | **Worker assertion + independent reviewer blocker**, with the reviewer load-bearing | Self-assertion by the worker that wrote the shim cannot be the gate (motive + rationalisation). The independent reviewer is the gate. |
| Measurement | **Disposition-violations counter** (counter 1), with a deferred second "general over-production" counter | Counter 1 is a diff against a recorded decision — auditable, not a self-judgement. The general counter measures a model self-blind-spot; deferred until the disposition record proves reliable. |

## Design

### 1. DECIDE — disposition fork, resolved up front

Sits alongside Phase 2.5 (resolve design forks before execution).

- **Trigger:** while writing the Phase 1 plan, the orchestrator flags any
  work-unit that **retires an existing code path** — there must be a named
  thing being replaced. Not merely "new code calls old code."
- **Ask once**, before the first spawn, bounded exactly like a Phase 2.5 design
  fork (ask once, don't loop):
  > clean-break (remove the old path; no shims / bridges / adapters / flags)
  > **vs** preserve-compat (keep the old path behind a shim, with a named
  > removal follow-up ticket).
- **Anti-laundering rule:** clean-break is the *stated default recommendation*
  for a retirement. preserve-compat is acceptable **only with a specific named
  blocker** — a named consumer still on the old path that cannot migrate now. A
  generic "safer for this migration" justification is rejected. This prevents the
  model laundering its preserve-prior into the human's explicit approval (which
  would make the failure invisible to the counter).
- **Record** per work-unit in `progress.json`: `disposition`, plus (if
  preserve-compat) `named_blocker` and a mandatory `removal_ticket`.

### 2. PROPAGATE — carry the decision into the worker (new Phase 3 step)

The disposition decision (and named blocker, if any) is copied **verbatim into
the spawned worker's self-contained task description** — not left only in
`progress.json`. The decision must survive the orchestrator→worker hop; a broken
hop silently reverts to today's behaviour.

### 3. ENFORCE — reviewer load-bearing, worker assertion secondary

- **Phase 4b (PRIMARY gate):** when `disposition=clean-break`, the
  code-simplifier reviewer (already an independent, read-only, separately-spawned
  agent) gets an explicit instruction to hunt **relabelled compat** —
  fallback / adapter / guard / transitional / bridge — and to check whether an
  **old code path still executes**, not whether the literal word "shim" appears.
  Findings are **MERGE-BLOCKERS**, not report-only suggestions.
  - **Override path:** the orchestrator may record "reviewed, not compat —
    `<reason>`" against a finding to demote a false-positive to a logged note.
    A misfire degrades to a note, never a wall.
- **Phase 3a (SECONDARY):** the worker's pre-push manifest assertion gains a
  clean-break line ("assert no compat shim/bridge/adapter/legacy path remains;
  if one does, clean-break is not finished"). Explicitly a first-pass smell test,
  **not** the gate. The reviewer is the gate.

### 4. MEASURE — Phase 13 scope-drift counter

- `disposition-violations`: work-units where `clean-break` was recorded but a
  shim/compat path shipped (caught at the gate, or by the human afterward).
  Audited as a diff between the `progress.json` disposition record and the merged
  artifact.
- **"0 violations" must be distinguished from "no disposition record found."**
  The latter reports as an **audit failure**, not a pass — otherwise the metric
  reads "factory clean" when the record was simply absent.
- preserve-compat units whose `removal_ticket` is still **open at loop end**
  surface as a separate drift signal, so compat debt cannot silently rot.

### Supporting change

`progress.json` schema (documented in the skill's Context-window-persistence
section) gains per-work-unit fields: `disposition`, `named_blocker`,
`removal_ticket`.

## Scope / YAGNI

- No new skill.
- No new agent — the reviewer is an extended code-simplifier pass (already
  independent of the worker).
- Edits confined to prose in Phases 0 / 2.5 / 3 / 3a / 4b / 13 + three
  `progress.json` fields.

## Planning-sequence findings folded in

Run via `/coderails:planning-sequence` on the pre-hardening design. The hardened
design above incorporates every finding:

- **Pre-Parade gap (propagation):** disposition must reach the worker prompt →
  added the PROPAGATE step.
- **Pre-Parade gap (record maintenance):** the counter depends on an unenforced
  `progress.json` → addressed by reordering Spec C ahead of B, and by the
  "no record found = audit failure" rule.
- **Pre-Parade gap (compat rot):** preserve-compat opens an untracked debt
  channel → mandatory `removal_ticket` + open-at-loop-end drift signal.
- **Premortem (self-attestation theatre):** worker that wrote the shim asserts
  it's gone → reviewer made load-bearing, worker assertion demoted.
- **Premortem (detection over-fire):** trigger tightened to "existing path being
  retired."
- **Premortem (false-positive deadlock):** override path so a misfire is a note,
  not a wall.
- **Premortem (counter measures a ghost):** "0 violations" vs "no record" must be
  distinguished.
- **Red Team (relabelling):** reviewer hunts fallback/adapter/guard/transitional
  and checks whether an old path still executes, not the word "shim."
- **Red Team (laundering the prior into approval):** anti-laundering rule —
  preserve-compat requires a specific named blocker.
- **Red Team (detection self-exemption):** concrete "named thing being retired"
  test is harder to self-exempt from.

## Known limitations

Spec A reduces shim frequency and makes the choice explicit and measurable, but
it does **not** fully close the hole on its own. Detection, the disposition
recommendation, and the worker assertion are all still self-judgements by the
model — the independent reviewer is the one hard check. The deepest closure
(mechanical enforcement of `progress.json` and the anti-stall behaviour) is
**Spec C**, now correctly sequenced to run immediately after A.

## Sequencing

1. **Spec A** — this document (clean-migration discipline). **DONE** — merged to
   `main` 2026-06-24 (commits `90601d5`..`d0a8dae`); 5 tasks, all task-reviews
   clean, final whole-branch review READY TO MERGE.
2. **Spec C** — mechanical anti-stall hook + `progress.json` reliability
   enforcement. Pulled ahead of B because A's counter and propagation both depend
   on `progress.json` being reliably maintained.
3. **Spec B** — slim the skill (extract project-specific Phases 7/8 to memory,
   compress war stories). Last, so the slim operates on final content.
4. **Spec D** — wire superpowers construction discipline into the loop's worker
   contract. Agentic-loop has *verification* discipline (artifact checks,
   confidence labels, premise-disproving) but no *construction* discipline — it
   says the Phase 3a worker "implements AND verifies its own artifact" without
   saying *how* to build. Spec D adds a thin **integration seam**: Phase 3/3a
   names `superpowers:test-driven-development` and
   `superpowers:subagent-driven-development` as the worker's construction method
   (a one-line reference, the way Phase -1 already references improve-prompt) —
   NOT absorbing or re-implementing them, which would break coderails'
   self-contained-zip property and bloat the skill (working against Spec B).
   Captured decisions for its design phase:
   - **Sonnet-only, no exceptions** — the subagent-driven reference must mandate
     `model: sonnet` for every worker, with no escalation path. This matches the
     agentic-loop rule that workers are always sonnet (cost control + the
     orchestration pattern); Spec D must not let superpowers' model-selection
     guidance reintroduce opus/most-capable workers.
   - **Reference, not vendor** — couple to superpowers skills by name, accept the
     advisory (not mechanical) nature; if TDD must be *enforced* in the loop, that
     is a hook (Spec C territory), not a skill reference.
   - Sequenced last because it edits Phase 3/3a (which Spec A just changed) and
     should land on the slimmed, stabilised skill.
   - Like B and C, Spec D gets its **own brainstorming + planning-sequence** before
     any spec doc is written. This entry is a placeholder for the decision, not a
     design.
