---
name: task-evals
description: 'Generate a frozen, game-resistant set of end-state success evals for any non-trivial task — inside an agentic loop or not. Invoked at task intake: by agentic-loop at Phase 2.7 (loop scope) and per-work-unit refs in worker prompts (pr scope), by writing-plans when a plan is written (pr scope), or directly by the user. Produces evals.json (schema_version 1) consumed by scripts/post_evals.sh (pr scope, gates /merge) or the loop-state dir (loop scope, gates LOOP-STOP: complete). Not self-verification — evals must not share an oracle with the implementation.'
---

# Task Evals

How to turn any non-trivial task into a frozen, tiered set of independent, game-resistant success evals — before implementation starts, not after.

## Why this skill exists

coderails verifies everywhere, but always self-verifies. `writing-plans` gives every task verify-criteria written by the same process that then implements against them. `agentic-loop` Phase 3/3a workers verify their own artifact; Phase 4b reviews code quality, not goal attainment; Phase 13 self-audits process counters, explicitly unscored. The `/merge` gate requires a SHA-bound review artifact — evidence that review happened, not that the task's goal state was reached. The one place coderails-adjacent work has had genuinely game-resistant acceptance evals is the hand-written public-readiness suite (E0–E10): negative controls, end-state assertions against fresh surfaces, independent GO/NO-GO gating, evals defined independently of task self-verification. This skill generalises that pattern. A model that wants to "pass" today writes its own verify-criteria, runs them itself, and grades itself — three conflicts of interest stacked. This skill exists to break that stack.

## The five anti-gaming rules

Every eval this skill generates must satisfy all five. These are generation requirements, not descriptions of an ideal — an eval that fails one of them is not a valid eval.

1. **Freeze-before-build.** Evals are generated and frozen (timestamp + base SHA) before implementation starts. Post-freeze edits are amendments with recorded reasons — visible, auditable, reported at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern). A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Assertions run against merged state, fresh clone, or deployed artifact — never working-tree self-reports.
4. **Oracle independence.** An eval must not share its oracle with the implementation (same regex, same fixture, same test the implementation writes). Derive evals from the task's goal state, not its implementation steps.
5. **Grader independence.** Judgement evals are graded by a fresh subagent that receives only `evals.json` + artifact references — never the implementation conversation. The orchestrator never hand-writes the `result` field; a neutral assembly script computes it.

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at`/`frozen_sha` on any eval, run this check against it once:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

This runs once per eval, immediately before freezing. An eval that fails the self-check is rewritten, not annotated or excused — there is no partial pass on this check.

## Tier rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Tier 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state. The exemption is still a written artifact — the gates accept a justified exemption, never an absence.
- **Tier 1 (standard):** anything above tier 0 that doesn't meet a tier-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Tier 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

## Eval anatomy

Each eval object in the `evals` array carries:

- **ID** — short identifier (e.g. `E1`).
- **Priority** — `P0` blocks the gate; `P1` must be fixed before announcing but doesn't block.
- **Mode** — `scripted` (deterministic command) or `agent-run` (judgement, graded by a fresh verifier subagent).
- **Surface** — `merged-state | fresh-clone | artifact-path | deployed`.
- **Assertion** — one-line goal-state assertion.
- **Command or verifier instruction** — the scripted command, or the instruction handed to the verifier subagent.
- **Negative control** — required for scripted mode: a command proving the check can fail.
- **Expected outcome** — what a pass looks like.

## GO/NO-GO rule

GO requires all P0 evals to pass. P1 failures don't block the gate but must be listed unresolved in the artifact — they are visible debt, not silently dropped.

## Schema (schema_version 1)

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

This is the single documented copy of the schema. `scripts/lib/eval-artifact.sh`, `scripts/post_evals.sh`, and the `loop_state_guard` loop-scope gate all implement against this definition — it does not get restated or drift elsewhere.

## Where evals.json lives

- **Loop scope** → the loop-state dir beside `progress.json` (path from `hooks/scripts/lib/agentic_loop_path.sh`), outside the repo, never committed.
- **PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment posted by `scripts/post_evals.sh` (marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> tier=<0|1|2> -->`) — see the invocation contract below.

## Invocation contract

This skill is invoked at three points:

- **agentic-loop Phase 2.7** — loop scope, alongside `spec.md`/`plan.md`.
- **writing-plans**, when a plan is written — pr scope, as the plan's final task.
- **Directly by the user.**

A plan's or loop's per-work-unit eval refs travel in worker prompts the same way disposition travels under agentic-loop Phase 3's existing pattern: a ref recorded only in `progress.json` and absent from the worker's own prompt does not exist for that worker. Every worker prompt that owns a unit with an eval ref must carry that ref verbatim, not just a pointer to the loop state file.

## Verifier agent contract (agent-run evals)

For agent-run evals, a fresh sonnet subagent is spawned to grade. Its prompt contains: the `evals.json` content, artifact references (PR number, clone path, deployed surface), and the confidence-label contract — and explicitly nothing else. It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion of the outcome — the same principle behind agentic-loop Phase 4b's clean-break gate (the author is the least able to see its own shims). The verifier returns per-eval status plus evidence; the assembly script (`post_evals.sh` for pr scope, a direct `evals.json` update for loop scope) folds the results in and computes `result` itself — the verifier never writes `result` directly.
