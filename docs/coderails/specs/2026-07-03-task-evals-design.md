# task-evals — Game-Resistant Success Evals for Any Task — Design Spec

## Goal

Give coderails the ability to turn any non-trivial task — inside an agentic loop or not — into a frozen set of independent, end-state success evals the implementing model cannot easily game, and to enforce (by hook, from day one) that work cannot be declared done without a passing eval artifact.

## Problem statement / context

coderails verifies everywhere, but always **self**-verifies *(verified against current sources 2026-07-03)*:

- `writing-plans` gives every task verify-criteria — written by the same process that then implements against them.
- `agentic-loop` Phase 3/3a workers verify their own artifact; Phase 4b reviews code quality (not goal attainment); Phase 13 self-audits process counters, explicitly unscored.
- The `/merge` gate (`scripts/merge.sh`) requires a SHA-bound **review** artifact — evidence that review happened, not that the task's goal state was reached.

The one place coderails-adjacent work has had genuinely game-resistant acceptance evals is the hand-written public-readiness suite (E0–E10): negative controls, end-state assertions against fresh surfaces, independent GO/NO-GO gating, evals defined independently of task self-verification. Nothing generalises that. A model that wants to "pass" today writes its own verify-criteria, runs them itself, and grades itself — three conflicts of interest stacked.

## Resolved decisions (owner-confirmed 2026-07-03, via AskUserQuestion in this session)

| Decision | Choice |
|---|---|
| Placement | Standalone skill (`coderails:task-evals`); agentic-loop and writing-plans both wire it in |
| Grading | Hybrid: scripted evals run as deterministic commands; judgement evals go to a fresh verifier subagent |
| Enforcement | **Hook-enforced from day one** (owner chose stronger than recommended skill-first option) |
| Scope | Tiered by task weight (0 = justified exemption, 1 = standard, 2 = full suite) |
| Enforcement shape | **Both seams, one schema**: per-PR evals gate `/merge`; loop-level evals gate `LOOP-STOP: complete` |

## Architecture

One new skill owns eval **generation**. One JSON schema (`evals.json`) serves two scopes. Two existing enforcement surfaces each grow one check:

- **`scope: "pr"`** — evals gate the merge. Result is posted as a SHA-bound machine-marked PR comment (the proven `post-review` artifact pattern); `scripts/merge.sh` gains a second fail-closed artifact gate beside the existing review-artifact gate. `enforce_pr_workflow.sh` is NOT touched — it enforces transcript evidence, not artifacts; artifact gates live in the merge script layer.
- **`scope: "loop"`** — evals gate loop completion. `evals.json` lives in the loop-state dir beside `progress.json`; the `loop_state_guard` hook family blocks a `LOOP-STOP: complete` when the loop's `progress.json` records ≥3 work-units but no sibling loop-scope `evals.json` with `result: "GO"` exists.

The anti-gaming core is constant across both scopes:

1. **Freeze-before-build.** Evals are generated and frozen (timestamp + base SHA) before implementation starts. Post-freeze edits are amendments with recorded reasons — visible, auditable, reported at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern). A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Assertions run against merged state, fresh clone, or deployed artifact — never working-tree self-reports.
4. **Oracle independence.** An eval must not share its oracle with the implementation (same regex, same fixture, same test the implementation writes). Derive evals from the task's goal state, not its implementation steps.
5. **Grader independence.** Judgement evals are graded by a fresh subagent that receives only `evals.json` + artifact references — never the implementation conversation. The orchestrator never hand-writes the `result` field; a neutral assembly script computes it.

## Components

### 1. Skill: `skills/task-evals/SKILL.md`

The generation method. Invoked at task intake — by agentic-loop at Phase 2.7 (loop scope, and per-work-unit pr scope refs carried in worker prompts), by writing-plans when a plan is written (pr scope), or directly by the user. Contents:

- The five anti-gaming rules above, as generation requirements.
- The tier predicates (below) and the requirement that tier-0 exemption still produces a written artifact.
- A mandatory gameability self-check before freezing: *"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*
- Eval anatomy: ID, priority (`P0` blocks, `P1` fix-before-announce), mode (`scripted`/`agent-run`), surface, assertion, command or verifier instruction, negative control (scripted mode), expected outcome.
- GO/NO-GO rule stated in the artifact: GO requires all P0 pass; P1 failures don't block but must be listed unresolved.

### 2. Schema: `evals.json` (schema_version 1)

```json
{
  "schema_version": 1,
  "scope": "pr | loop",
  "task_ref": "<branch/PR# for pr scope; session loop ordinal for loop scope>",
  "tier": 0,
  "tier_justification": "<required when tier is 0>",
  "frozen_at": "<ISO8601>",
  "frozen_sha": "<base SHA at freeze>",
  "evals": [
    {
      "id": "E1",
      "priority": "P0",
      "mode": "scripted",
      "surface": "merged-state | fresh-clone | artifact-path | deployed",
      "assert": "<one-line goal-state assertion>",
      "cmd": "<command, scripted mode>",
      "negative_control": "<command proving the check can fail — required, scripted mode>",
      "status": "pending | pass | fail",
      "evidence": "<command + exit code + output excerpt>"
    }
  ],
  "amendments": [ { "eval": "E1", "when": "<ISO8601>", "why": "<reason>" } ],
  "result": null,
  "graded_at": null,
  "head_sha": "<SHA the grading ran against>"
}
```

Storage: loop scope → loop-state dir beside `progress.json` (path from `agentic_loop_path.sh`, outside the repo, never committed). PR scope → the file is working material; the durable artifact is the PR comment (below).

### 3. PR-scope artifact: marker + writer + reader

- **Marker SSOT**: new `scripts/lib/eval-artifact.sh`, sibling of `review-artifact.sh`, one constructor sourced by writer and reader. Marker shape: `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> tier=<0|1|2> -->`. Exact-line equality matching, unknown versions never match (fail-closed) — same contract as the review marker.
- **Writer**: `scripts/post_evals.sh` (+ thin command doc). Validates structure before posting — refuses if: tier ≥1 and any scripted eval lacks a non-empty `negative_control`; any P0 lacks `evidence`; `result` inconsistent with per-eval statuses; `head_sha` ≠ current PR head. Computes `result` itself from per-eval statuses (the neutral party — the orchestrator never writes it). Tier-0 path posts an exemption artifact carrying the justification instead of eval results.
- **Reader**: `scripts/merge.sh` gains a second gate directly after the review-artifact gate, same fail-closed semantics: GitHub fetch failure → block with retry message; no matching marker for current head → block with remediation hint; marker present but `result=NO-GO` → block. Tier-0 exemption marker satisfies the gate.

### 4. Loop-scope gate: `loop_state_guard` family extension

Extend `hooks/scripts/lib/loop_state_common.sh` + `loop_state_guard.sh` (exact function placement is the plan's decision): when a stop would be allowed because the loop is `complete`, additionally require — if `progress.json` records ≥3 work-units — a sibling `evals.json` with `scope: "loop"` and `result: "GO"` (or `tier: 0` with justification, which for a ≥3-unit loop should be rare and is expected to draw human attention in the Phase 13 report). Absent or NO-GO → exit 2 with a remediation message naming the exact path, matching existing guard UX. The tier trigger is hook-legible by construction: work-unit count is already in `progress.json`. Note the deliberate floor: the hook enforces only the count-based tier-2 trigger; the surface-based trigger (irreversible/outward work in a <3-unit loop) is not hook-legible at the Stop seam and remains skill discipline — such work ships via PRs, where the merge-gate seam still catches it.

### 5. Verifier agent contract (agent-run evals)

Fresh sonnet subagent. Prompt contains: the `evals.json` content, artifact references (PR number, clone path, deployed surface), the confidence-label contract — and explicitly nothing else. It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion of the outcome (Phase 4b principle: the author is the least able to see its own shims). It returns per-eval status + evidence; the assembly script (`post_evals.sh` for pr scope; direct `evals.json` update for loop scope) folds results in and computes `result`.

### 6. Wiring edits

- **`skills/agentic-loop/SKILL.md`**: Phase 2.7 gains a sub-step — generate and freeze loop-scope evals via `/coderails:task-evals` alongside `spec.md`; worker task descriptions carry per-unit eval refs the same way disposition travels; Phase 13 runs the loop suite before declaring complete and reports amendments unscored (alongside disposition violations). The "no eval record found" vs "evals passed" distinction mirrors Phase 13's existing "0 violations" vs "no record" rule: an absent record is an audit failure, not a pass.
- **`skills/writing-plans/SKILL.md`**: plans grow a final eval-gate task; per-task verify-criteria remain as cheap inner-loop checks, but the plan's *done* is the eval artifact.
- **`commands/merge.md` / `commands/workflow.md`**: document the eval artifact requirement beside the existing post-review artifact requirement.

## Tier rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?":

- **Tier 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state. The exemption is still a written artifact — the gates accept a justified exemption, never an absence.
- **Tier 1 (standard):** anything above tier 0 that doesn't meet a tier-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Tier 2 (full suite):** ≥3 work-units (the line Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

## Honest boundaries

The gates verify **existence, SHA binding, and structure** — result field is GO, negative-control and evidence fields non-empty where required. They cannot verify eval *quality* or evidence *honesty*. Same declared boundary as `loop_state_guard` ("presence + ownership, not content") and `check_verify_loop.sh`. Mitigations are structural (freeze + amendments log + neutral result computation + hook-visible negative-control fields) and social (Phase 13 reports amendments and tier-0 exemptions unscored for the human to judge). A determined model can still write weak evals; what it can no longer do is skip, silently edit, or self-grade them.

Known bypass surface (accepted, consistent with existing gates): the settings.json Bash-permission escape documented in `enforce_pr_workflow.sh` applies to `gh pr merge` generally; a human can always bypass. The gate constrains the model, not the owner.

## Acceptance criteria (this feature's own evals)

This feature ships gated by the discipline it introduces. Scripted, all P0 unless noted:

- Merge gate blocks: missing eval artifact; artifact for stale head SHA; `result=NO-GO`; tier≥1 artifact whose scripted evals lack negative controls (writer refuses to post it, so the on-PR artifact can't exist in that state — asserted at the writer).
- Merge gate passes: GO artifact bound to current head; tier-0 exemption artifact.
- Loop gate blocks: `complete` with ≥3 work-units and no loop `evals.json`; present but NO-GO.
- Loop gate passes: GO present; <3 work-units with no evals file (tier trigger not met).
- Negative control for the gates themselves: each blocking test's fixture, run against the pre-extension hook/script, must PASS the old gate — proving the new tests detect the new behaviour, not something that was always true.
- All existing tests in `hooks/scripts/tests/run_all.sh` stay green.
- (P1, agent-run) A fresh subagent given only `skills/task-evals/SKILL.md` and a sample task produces a suite where every scripted eval has a working negative control.

## Residual risks (accepted)

- Eval quality remains model-dependent; the structure forces the *shape* of good evals, not their insight. The human sees amendments and exemptions at Phase 13 and in PR artifacts.
- Two gates share one schema but have separate lifecycles; drift between them is possible. Mitigated by the marker/schema SSOT files and shared tests, not eliminated.
- Cost: tier-1+ tasks pay an extra artifact round-trip and (when judgement evals exist) one verifier agent spawn. Accepted — the alternative is self-attestation.
- The now-deleted `skills/planning-sequence/evals/evals.json` (removed in PR #55; was the skill-creator quality-eval schema) was a different animal — skill-quality evals, not task-success evals — and was deliberately never unified with this schema (YAGNI; see memory `project_skill_eval_runner_decision`).
