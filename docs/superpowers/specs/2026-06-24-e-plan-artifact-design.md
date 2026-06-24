# Spec E — Spec→Plan artifact discipline

**Status:** design, awaiting review
**Branch:** `spec/e-plan-artifact`
**Date:** 2026-06-24
**Part of:** the agentic-loop upgrade sequence A → C1 → C2 → B → D → **E** (A/C1/C2/B/D merged as PRs #12/#13/#14/#15/#16). E is last in the arc.

## Problem

superpowers' build chain has three artifacts: **spec → plan → progress**. A spec captures *what we decided and why*; a plan captures *the durable decomposition* (tasks with exact files, interfaces, verify-criteria); progress tracks *where we are* against the plan. The agentic-loop reimplemented only the third. C1/C2 gave it a reliable, owned, guard-enforced `progress.json` — the dynamic cursor — but the loop still dispatches Phase 3 workers from **ephemeral Phase 1 bullets**. There is no durable spec doc and no durable plan doc.

That is a real gap, not a cosmetic one:
- **Worker scope is undocumented.** Phase 3/3a task descriptions are assembled from conversation state. After a compaction the orchestrator re-reads `progress.json` (position) but has no durable record of the *decomposition* — the work-unit boundaries, the per-unit files/interfaces, the verify-criteria. It has to re-derive them, and re-derivation drifts.
- **The design forks evaporate.** Phases 2.5/2.6 resolve design and disposition forks, and record the *decision* in `progress.json` — but not the reasoning, the rejected alternatives, or the flip-condition in a form that survives as a spec. The "why" lives only in the conversation, which compacts away.
- **`progress.json` is a cursor with nothing to point at.** A position artifact is only as good as the static SSOT it indexes. Without a `plan.md`, "work-unit 2 is in-progress" references bullets that no longer exist verbatim.

E adds the two missing **durable artifacts** — a `spec.md` and a `plan.md` — so the loop's construction discipline matches its verification discipline, and the orchestrator can re-derive *what to build* (not just *where we are*) from disk after any compaction.

## Approved decisions (brainstormed with Gary 2026-06-24, all 4 confirmed)

1. **Both artifacts.** The loop writes a durable `spec.md` AND a durable `plan.md` before Phase 3 dispatch. Not one or the other — the spec is the design record, the plan is the decomposition; they serve different readers (the spec justifies, the plan instructs).

2. **Spec = in-line loop phase; Plan = vendored skill.**
   - The **spec** is written by a new in-line loop phase. This is deliberate and matches superpowers' own division: superpowers writes a spec via *interactive brainstorming with a human*, but **a loop cannot brainstorm with itself**. By the time the loop reaches this phase the design is already resolved — the envelope (Phase 0), the design fork (Phase 2.5), the disposition (Phase 2.6). The spec phase **commits that already-resolved design to disk**; it does not re-open it. So it is an in-line write, not a delegated skill.
   - The **plan** is written via a **vendored `coderails:writing-plans` skill** — adapted from superpowers' writing-plans, focused, coderails-owned, with **no cross-plugin dependency**. This is the same approach Spec D took for TDD: vendor the discipline so the plugin stays a self-contained zip. A new loop phase references the skill the way Phase 3/3a reference `coderails:test-driven-development`.

3. **Doc location = the loop state dir, NOT committed.** Both docs are written next to `progress.json` in `~/.claude/agentic-loop/<slug>/`, the path resolved by the existing `agentic_loop_path.sh` helper (Phase -2). This is **outside the code repo** (honours Phase 2.5's anti-pollution rule — loop state never lands on local `main` or in a worker's base), cwd-keyed (survives compaction and session restart), and **not committed** — these are loop *state*, not PR deliverables. `plan.md` is the static SSOT; `progress.json` is the dynamic position against it. (The spec docs under `docs/superpowers/specs/` in *this* repo are a different thing — they are the upgrade's own design record, committed because coderails is the product. A loop running *in some other project* writes its `spec.md`/`plan.md` to that project's loop-state dir, uncommitted.)

   **Tradeoff acknowledged (Red Team):** uncommitted + machine-local means a teammate or a different machine picking up the branch sees no `spec.md`/`plan.md`. That is deliberate and correct — they are loop *state* keyed to one orchestrator's run, exactly like `progress.json`, not a shareable design record. The shareable design record is the committed spec under `docs/` (for a real product) or, when ad-hoc loop work genuinely needs to be handed to a human, the loop already has `coderails:handoff` for that. E does not change where shareable records live; it adds where *loop-internal* decomposition lives.

4. **Complexity guard (like D's code-guard).** The spec/plan phases fire ONLY when the loop has **≥3 work-units or a cross-unit dependency** — *exactly* the line Phase 3 already draws to choose `TeamCreate` over a single Agent (Phase 3 routes 1–2 self-contained units to one agent, and reserves `TeamCreate` for "3+ PRs or any cross-step dependency"). A 1–2-unit fix that Phase 3 itself calls single-agent-simple needs no separate design docs: the envelope (Phase 0) + `progress.json` + the one self-contained task description already carry everything. Forcing a `spec.md`/`plan.md` onto single-agent work would be ceremony, and ceremony that fires on trivial work trains the loop to skip it on real work. Pinning the guard to Phase 3's own multi-unit-team threshold keeps the artifacts where they pay for themselves AND avoids an internal contradiction (an earlier draft said "≥2", which would demand a formal spec+plan for work Phase 3 routes to a single agent — corrected here after the planning-sequence flagged it).

## Reachability (to confirm during planning-sequence)

The seam must actually *fire*, not just exist — the same bar Spec D held itself to:
- **The path helper is already the sole authority.** Phase -2 runs `agentic_loop_path.sh` and the loop already writes `progress.json` to the resolved dir. Writing `spec.md`/`plan.md` to the *same* dir reuses an established, working mechanism — no new path computation, no model-computes-the-hash deadlock (the C1 failure mode).
- **The skill-reference idiom is established.** Phase -1 references `/coderails:improve-prompt`; Phase 3/3a reference `coderails:test-driven-development`. `coderails:writing-plans` follows the exact same namespaced idiom, and a Phase 2 spawned agent already "invokes each relevant skill via its `Skill` tool call" — so a plan phase that says "produce `plan.md` via `coderails:writing-plans`" is reachable by the same path D's TDD reference is.
- **The complexity guard reuses an existing threshold.** "≥3 work-units or a cross-unit dependency" is the *same* condition Phase 3 already uses to choose `TeamCreate` over a single Agent. The guard is not a new judgement call — it is the one the loop already makes at Phase 3, pulled one phase earlier.

The honest boundary (same as the C1/C2 hooks and D's seam): E guarantees the loop is *told* to write the two artifacts and *can* reach the path + skill — not that it mechanically did. E is the **advisory construction-artifact layer**; mechanical enforcement (a hook that blocks Phase 3 dispatch when `plan.md` is absent) is explicitly deferred (see Out of scope).

## Constraints

- **C1/C2 no-touch regions stay byte-identical to `origin/main` — INCLUDING `## Context-window persistence`.** This is the primary constraint and the primary verification gate. The six regions are: (1) the frontmatter `description:` line (single-quoted), (2) the `### Phase -2` stub-first block, (3) the Phase 0.5 LOOP-STOP bullet, (4) the Phase 13 KPI bullet, (5) the Stop-conditions "Declaring the stop" block, (6) the entire `## Context-window persistence` section. The persistence section *describes `progress.json`* — it is tempting to extend it to mention `spec.md`/`plan.md`, but that edit is forbidden. **Describe the new artifacts entirely within the new Phase 2.7/2.8 prose.** The persistence section stays byte-stable.
- **Additive phases, no renumber.** The two new phases are `2.7` and `2.8`, inserted after `2.6` and before `3`. No existing phase is renumbered. (Decimal phase numbers are already the skill's established pattern for insertions — -2, -1, 0, 0.5, 2.5, 2.6, 3a — so 2.7/2.8 fit without disturbing the integer sequence Phase 13's audit or any cross-reference relies on.)
- **No cross-plugin dependency.** The vendored `coderails:writing-plans` skill is coderails-owned; the Phase 2.8 reference uses the `coderails:` namespace. No `superpowers:` reference ships in the skill text or the new phases.
- **Sonnet-only untouched.** The new phases must not introduce any model-selection guidance that could escalate workers off sonnet. The vendored skill is *how to plan*, not *which model* — it carries no model guidance (same rule D held for TDD).
- **Tie E→D.** The vendored writing-plans skill's per-task construction step **references `coderails:test-driven-development`** — a plan's tasks carry the construction method, closing the loop between E (decomposition) and D (construction). This is the natural place the two specs meet.
- **Don't regress B's slim.** The two new phases are tight — a complexity-guard sentence, what to write, where, and the skill reference. Not a re-expansion of the bulk Spec B just cut.

## Deliverable 1 — `skills/writing-plans/SKILL.md` (+ any companion)

A new coderails skill, built with skill-creator, adapting superpowers' writing-plans discipline into coderails' voice and namespace. Self-contained, no cross-plugin reference, focused — **adapt to a tight skill, not a verbatim copy** of the full superpowers file (the same lesson D applied: an over-long skill is a worse trigger and re-imports bulk B cut).

**Frontmatter:**
- `name: writing-plans` (invoked as `coderails:writing-plans`; namespace prevents collision with `superpowers:writing-plans`).
- `description:` single-quoted (per commit `e6e39dd`, strict-YAML safe). It triggers when there is a resolved spec/decomposition to turn into a durable, task-by-task plan — *before* implementation. Example shape: `'Use when you have a spec or resolved design for a multi-step task and need a durable, task-by-task implementation plan before any code is written — each task with exact files, interfaces, bite-sized steps, and verify-criteria. Not for single trivial edits, which need no separate plan.'` The "not for single trivial edits" clause is the skill-level echo of Phase 2.8's complexity guard.

**Body (adapted, coderails voice):**
- What a plan is: an ordered set of **self-contained tasks**, each one dispatchable to a worker without re-reading the conversation. (This is exactly the Phase 3 "self-contained task description" contract — the skill and the loop agree by construction.)
- Each task carries: exact files to create/modify, the interfaces/signatures touched, bite-sized ordered steps, and **verify-criteria stated as something testable**.
- **Per-task construction method references `coderails:test-driven-development`** — when a task's deliverable is code (adds/alters a function, method, or branch that can carry a test), the plan instructs test-first construction. This is the E→D tie.
- DRY / YAGNI / no-placeholders discipline: a plan task says exactly what to build, no speculative flexibility, no `TODO`/stub left for "later".
- A self-review gate: before the plan is final, re-read it against the spec — every spec requirement maps to a task, every task traces to a requirement.
- Drop superpowers-specific framing and padding.

**Build process — skill-creator genuinely run.** The skill is built via skill-creator AND its **description-optimization loop is genuinely run** (`run_loop.py`, model `claude-sonnet-4-6`, with should-trigger and should-NOT-trigger eval queries — the negatives protect the complexity-guard clause). This is non-negotiable: a Spec D worker only `mkdir`'d and Gary caught it, forcing a follow-up opt run. Delegate to a sonnet agent that invokes skill-creator via the `Skill` tool and runs the loop; guard the result by keeping the single-quoting and the "not for single trivial edits" exclusion clause.

**Registration:** none required. Claude Code auto-discovers `skills/*/SKILL.md`; plugin.json does not enumerate skills and install.sh does not touch them (verified for D — same applies here). Optional cosmetic polish: add `writing-plans`/`planning` to plugin.json `keywords` — not load-bearing.

## Deliverable 2 — two additive agentic-loop phases (2.7, 2.8)

Both inserted after Phase 2.6 and before Phase 3, both gated by the complexity guard, no renumber of any existing phase.

### Phase 2.7 — Commit the resolved design to a durable `spec.md`

Fires only when the loop has **≥3 work-units or a cross-unit dependency** — Phase 3's own `TeamCreate` line (otherwise skip — the envelope + `progress.json` + the one task description suffice for single-agent work). When it fires, write a durable `spec.md` to the loop-state dir (the path from `agentic_loop_path.sh`, next to `progress.json`, outside the repo, uncommitted). The spec records the design the loop has **already resolved** by this point — it does not re-open any fork:
- the authorisation envelope verbatim (Phase 0);
- the design-fork decision and its flip-condition (Phase 2.5), and the disposition decisions with named blockers (Phase 2.6);
- the success criteria — what "done" means for the whole loop;
- the work-unit boundaries at a high level (the detailed decomposition is Phase 2.8's plan).

State explicitly that this is a *commit of resolved design, not interactive brainstorming* — a loop cannot brainstorm with itself; the forks were closed at 2.5/2.6.

### Phase 2.8 — Write the durable `plan.md` via `coderails:writing-plans`

Fires under the same complexity guard. Produce a durable `plan.md` in the loop-state dir (next to `spec.md`/`progress.json`, uncommitted) by invoking **`coderails:writing-plans`**. The plan is the **decomposition Phase 3's `TeamCreate` / worker descriptions derive from** — its tasks become the Phase 3 task list, so the two are consistent by construction rather than re-derived.

**`plan.md` is consumed, not write-only — state this explicitly in the phase** (the planning-sequence's sharpest finding: a written-once-never-read artifact is ceremony, not discipline). Phase 2.8 must say both directions of consumption: (a) **Phase 3 builds its task list directly from `plan.md`** rather than from conversation state, and (b) **after any compaction the orchestrator re-reads `plan.md` to recover *scope* (what to build) the same way it re-reads `progress.json` to recover *position* (where we are)**. The re-read instruction lives **here, in Phase 2.8** — NOT in the `## Context-window persistence` section, which is a no-touch region describing `progress.json` alone. Naming the relationship is what makes `plan.md` the **static SSOT** and `progress.json` the **dynamic position** against it; this is the one place the relationship is stated, and it is stated standalone so the persistence section need not be touched.

**Placement and the guard wording.** Both phases lead with the complexity guard as their first sentence (so a sub-threshold loop skips them immediately, not after reading the body) and reuse the established one-line skill-reference idiom for 2.8. Neither phase touches the `model: sonnet` rule or any no-touch region.

**Plan-time worker-prompt guard (the Task 2 implementer must NOT edit the persistence section).** The new phases describe loop-state artifacts — which makes the `## Context-window persistence` section (also about loop-state artifacts) an attractive place for a worker to "helpfully" add a `plan.md` sentence, silently failing the byte-diff gate. So the Task 2 worker prompt (set at plan time) must carry **verbatim**: the six no-touch region anchors; the instruction "describe the new artifacts ONLY inside Phase 2.7/2.8, NEVER by editing the persistence section or any other no-touch region"; and a **pre-push self-assertion** — "before you push, run `git diff origin/main -- skills/agentic-loop/SKILL.md` and confirm every hunk falls between Phase 2.6 and Phase 3 and NO hunk intersects the six no-touch regions; if any does, STOP and report." This is the same first-pass-smell-test discipline Phase 3a already uses for manifest/disposition assertions; the byte-diff gate (Verification 6) remains the actual gate.

## Verification

The byte-diff gate is primary; token-greps are necessary-not-sufficient (Spec B's planning-sequence finding: a keyword can survive while its sentence is clipped, so a grep alone never proves a region intact).

1. **New skill loads.** `skills/writing-plans/SKILL.md` exists with valid single-quoted frontmatter; any companion exists and is linked. The `description` contains the complexity-guard exclusion clause ("not for single trivial edits" or equivalent).
2. **skill-creator genuinely run.** Evidence the description-optimization loop actually executed (eval queries incl. should-NOT-trigger negatives, a score), not just a `mkdir`. The kept description is the optimizer's result, single-quoted, exclusion clause intact.
3. **E→D tie present.** The vendored skill body references `coderails:test-driven-development` in its per-task construction step.
4. **Two additive phases, complexity-guarded.** Phase 2.7 and Phase 2.8 exist between 2.6 and 3. Each leads with the **≥3-work-units-or-dependency** guard (matching Phase 3's `TeamCreate` line — confirm the wording does NOT say "≥2"). Phase 2.8 references `coderails:writing-plans` AND states both consumption directions (Phase 3 derives its task list from `plan.md`; orchestrator re-reads `plan.md` for scope post-compaction). No existing phase renumbered (grep the phase headings list — -2,-1,0,0.5,1,2,2.5,2.6,2.7,2.8,3,3a,4,4b,5,6,7&8,9,10,11,12,13 in order).
5. **Doc location correct.** The new phases write `spec.md`/`plan.md` to the `agentic_loop_path.sh` dir (next to `progress.json`), state they are outside the repo and uncommitted. No phase says to commit them or write them into the repo tree.
6. **C1/C2 no-touch regions byte-identical.** `git diff origin/main -- skills/agentic-loop/SKILL.md` — every hunk falls between Phase 2.6 and Phase 3; no hunk intersects any of the six no-touch regions. **`## Context-window persistence` is byte-identical** (diff shows zero lines in it). Frontmatter `description:` byte-identical.
7. **No dependency leak.** Grep the whole branch diff for `superpowers:` in shipped skill/skill-phase text — the plan reference points at `coderails:writing-plans`, not `superpowers:`.
8. **Sonnet-only intact.** The new phases and the new skill contain no model-selection guidance that could escalate a worker off sonnet (grep new skill + new phases for `opus`/`most capable`/`model:` → none, or only an orthogonality note).
9. **Hooks still green.** The three hook suites (path 3/3, state-guard 8/8, stall-guard 8/8) pass — E is markdown-only, so they should be unaffected.

## Out of scope

- **No enforcement hook** that blocks Phase 3 dispatch when `plan.md` is absent. E's seam is advisory by design, like D's. A mechanical "no dispatch without a plan" gate is PreToolUse-hook territory (Spec C lineage) and is deferred.
- **No edit to `## Context-window persistence`.** The relationship between `plan.md` (SSOT) and `progress.json` (cursor) is named in Phase 2.8 only; the persistence section stays byte-stable.
- **No `subagent-driven-development` skill** (already ruled out in D — agentic-loop embodies orchestration).
- **No changes to hooks, `hooks.json`, `install.sh`, or `lib/` scripts** — E is a new skill + additive markdown phases only.
- **The deferred `tsh ssh` Phase 4/12 illustrative-example cleanup** (out of B/D scope) — could be batched here as a trivial extra, decided at plan time, but is not core to E. After E ships, it is the last item in the upgrade arc.
