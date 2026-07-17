---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, tiered set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
---

# Task Evals

How to turn any non-trivial task into a frozen, tiered set of independent, game-resistant success evals — before implementation starts, not after.

## Why this skill exists

coderails verifies everywhere, but always self-verifies. `writing-plans` gives every task verify-criteria written by the same process that then implements against them. `agentic-loop` Phase 3/3a workers verify their own artifact; Phase 4b reviews code quality, not goal attainment; Phase 13 self-audits process counters, explicitly unscored. The `/merge` gate requires a SHA-bound review artifact — evidence that review happened, not that the task's goal state was reached. The one place coderails-adjacent work has had genuinely game-resistant acceptance evals is the hand-written public-readiness suite (E0–E10): negative controls, end-state assertions against fresh surfaces, independent GO/NO-GO gating, evals defined independently of task self-verification. This skill generalises that pattern. A model that wants to "pass" today writes its own verify-criteria, runs them itself, and grades itself — three conflicts of interest stacked. This skill exists to break that stack.

## Prerequisite: gather context before generating evals

Before drafting a single eval, gather target context — wiki first, codebase only where the wiki doesn't cover it. The project wiki is cheaper to read and often already states the invariants and constraints the goal state must respect, prior decisions, and known gotchas that a codebase read would have to re-derive. Fall back to the codebase only for what the wiki leaves uncovered. If the project has no wiki (`config.wiki_path` is null), the context read is codebase-only.

This read is dispatched to a sonnet agent, not done inline: keeping the context-gathering step off the main thread keeps the orchestrator's context clean and makes the read auditable as a discrete, reportable step, the same delegation pattern `agentic-loop` Phase 2 uses for its pre-flight checks. The agent returns distilled findings, not raw file dumps. Inside an agentic loop, the orchestrator's Phase 2 pre-flight wiki read already satisfies this prerequisite — reuse its findings rather than re-reading per invocation.

This is a context-gathering prerequisite, not a verification step — do not conflate it with the gameability self-check or the six anti-gaming rules below.

## The six anti-gaming rules

Every eval this skill generates must satisfy all six. These are generation requirements, not descriptions of an ideal — an eval that fails one of them is not a valid eval.

1. **Freeze-before-build.** Evals are generated and frozen (timestamp + base SHA) before implementation starts. Post-freeze edits are amendments with recorded reasons — visible, auditable, reported at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern). A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Assertions run against merged state, fresh clone, deployed artifact, or a locally built artifact driven directly (rule 6's pr-scope `artifact-path`) — never working-tree self-reports: driving a locally run artifact observes end-state behaviour; a self-report just quotes the diff.
4. **Oracle independence.** An eval must not share its oracle with the implementation (same regex, same fixture, same test the implementation writes). Derive evals from the task's goal state, not its implementation steps. At loop scope, the task's goal state is taken from **`authorising_prompt_raw` as recorded in `progress.json`** — the post-Phase-0 envelope, exactly one canonical string, with no judgement call about which version of the prompt counts. `spec.md` does restate the loop's success criteria (Phase 2.7a), and `plan.md` restates it per-task — but this is a precedence rule, not a content denial: `spec.md`/`plan.md` supply constraints and concrete assertable surfaces, and their restated criteria never override the envelope's goal state as the eval author's anchor. `progress.json`'s field is the canonical source; `spec.md`'s copy (Phase 2.7a) is a derived restatement, not an independent authority.
5. **Grader independence.** Judgement evals are graded by a fresh subagent that receives only `evals.json` + artifact references — never the implementation conversation. The orchestrator never hand-writes the `result` field; a neutral assembly script computes it. An eval amended after a grader verdict returns to a fresh grader for re-grading; the orchestrator never writes a per-eval `status` that flips an existing verdict.
6. **Strongest surface.** If the task's goal state names something a human sees or interacts with — a UI, CLI output, a rendered artifact, a served endpoint — at least one P0 eval must exercise that surface directly: drive the running artifact (browser, CLI invocation, HTTP request), never only code-greps of merged state. At pr scope pre-merge this means the locally-run artifact (surface: `artifact-path`); at loop scope, the deployed surface. This is a writer-side generation rule: no script can detect "user-facing", so it is enforced at generation and by review, not by a gate. (Exemplar: the run-output noise-strip loop — merged-state greps passed while the live streaming window still leaked; only an in-browser eval across the streaming lifecycle caught it.)

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at`/`frozen_sha` on any eval, run this check against it once:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

This runs once per eval, immediately before freezing. An eval that fails the self-check is rewritten, not annotated or excused — there is no partial pass on this check.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freezing, execute every scripted eval's `cmd` and its `negative_control` once, for real, and read the raw output. This is a different question from rule 2 and from the self-check above: the negative control proves a check *can fail*; the smoke-run proves the check *can execute at all*. A negative control can pass cleanly while the `cmd` it pairs with never runs — so passing the self-check does not satisfy this step, and this step does not substitute for the self-check either. Both are required.

A broken instrument looks like this in the raw output: a reporter-loading error instead of a test summary, a module-resolution error (e.g. `ERR_MODULE_NOT_FOUND`) instead of an install log, a stack trace where an assertion result should be, or a gate/policy denial instead of the command's own output. In every case the tell is the same — the output shows the command never reached the artifact it claims to check, even though the process exited non-zero and would otherwise read as a passing "fail."

What to do on discovery depends on timing: at freeze time the file is not yet frozen, so a broken `cmd` or `negative_control` is simply rewritten and re-run — no amendment needed, nothing to record. Discovered after `frozen_at`/`frozen_sha` are stamped, it goes through the amendment path instead: recorded reason, assertion left unchanged, and if a grader verdict already exists for that eval, a fresh re-grade per rule 5.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A frozen, blind-authored scripted check can be broken in itself — incapable of ever passing (false alarm) or ever failing (vacuous) — and the smoke-run above does not catch this, because it only proves the check *executes*, not that its verdict *tracks the input*. Real instance (loop 8b69e779): an awk formula that exited 1 unconditionally, so a genuine 39/39 pass and a genuine 18/40 fail produced identical exit codes and could never pass for any code state.

An eval may carry an optional `fixtures` object on top of the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

When present, `scripts/post_evals.sh validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula and requires opposite outcomes (good exits 0, bad exits non-zero) — rejecting the eval, by name, if both fixtures produce the same exit code (non-discriminating) or if the formula can't be reasonably derived from `cmd` (fail-closed, asks the author to supply `fixtures.formula` explicitly).

**Honest boundary, stated plainly:** this gate validates only checks that carry `fixtures`. Checks without `fixtures` are grandfathered — validated exactly as they were before this gate existed, with zero behaviour change. Adding `fixtures` to an eval is opt-in, never retroactive: freezing this gate does NOT retroactively validate any existing eval or evals.json that predates it, and an author who never adds `fixtures` gets no discrimination proof at all. And even where `fixtures` is present, a pass only proves the formula CAN discriminate between these two specific inputs — it proves nothing about whether the formula tests the RIGHT claim, whether `cmd` and `fixtures.formula` stay in sync after edits, or whether the fixtures themselves are representative. This gate closes the "never fails" class of defect; it is not a general correctness proof of the check.

## Tier rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Tier 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state. The exemption is still a written artifact — the gates accept a justified exemption, never an absence. Anything rule 6 names — something a human sees or interacts with (a UI, CLI output, a rendered artifact, a served endpoint) — **is** an outward surface for this predicate: a user-facing change is minimum tier 1 and carries rule 6's ≥1 P0 drive-the-artifact eval. (This widens only the tier-0 test: tier 2's outward predicate stays scoped to its own parenthetical list — publish, deploy, migration, data deletion, external send — so user-facing alone does not escalate past tier 1.)
- **Tier 1 (standard):** anything above tier 0 that doesn't meet a tier-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Tier 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

`tier_justification` is required at every tier, not only tier 0: at tier 0 it states why the exemption is legitimate; at tier 1/2 it names which predicate fired (e.g. "2 work-units, no irreversible surface" or "≥3 work-units"). A blank justification is refused by the writer (`post_evals.sh validate-structure`, check 2) at pr scope, and by the loop gate (`loop_state_guard.sh` via `als_read_loop_evals_result`) at loop scope — the pr-scope MERGE reader itself only parses the posted marker comment (result/tier, no justification field), so enforcement there is entirely writer-side, at post time.

## Eval anatomy

Each eval object in the `evals` array carries:

- **ID** — short identifier (e.g. `E1`).
- **Priority** — `P0` blocks the gate; `P1` must be fixed before announcing but doesn't block.
- **Mode** — `scripted` (deterministic command) or `agent-run` (judgement, graded by a fresh verifier subagent).
- **Surface** — `merged-state | fresh-clone | artifact-path | deployed`. `artifact-path` covers a locally built or locally run artifact: a file path, a local CLI invocation, or a locally served endpoint (pre-merge builds of the change; the same endpoint on the live post-merge instance is `deployed`).
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
  "tier_justification": "<required at every tier: tier 0 = why the exemption is legitimate; tier 1/2 = which tier predicate fired>",
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
      "fixtures": "<OPTIONAL, scripted mode only: {good, bad, formula?} — see 'Discriminating-check gate' above. Absent = grandfathered, unvalidated by that gate>",
      "status": "pending | pass | fail",
      "evidence": "<command + exit code + output excerpt>"
    }
  ],
  "amendments": [ { "eval": "E1", "when": "<ISO8601>", "why": "<reason>", "regraded_by": "<fresh grader run — required only for amendments made after a grader verdict>" } ],
  "result": null,
  "graded_at": null,
  "head_sha": "<SHA the grading ran against>"
}
```

`grading` (`{by, checksum, amendments_at_grade}`) is write-time provenance, absent at freeze and written only when `post_evals.sh grade-loop` grades a loop-scope file (see the Verifier agent contract below) — optional and additive; pr-scope files and every existing reader tolerate its absence. Adding it does not bump `schema_version` past 1.

This copy and the design spec's copy are kept in lockstep; the enforcement components implement against this definition: `scripts/lib/eval-artifact.sh` (the marker/result SSOT), `scripts/post_evals.sh` (structural validation + result computation + `validate-discriminating`'s fixtures gate, invoked by `/coderails:post-evals`), and the `loop_state_guard` loop-scope gate (blocks loop completion at ≥3 work-units with no passing loop-scope `evals.json`).

## Where evals.json lives

- **Loop scope** → the loop-state dir beside `progress.json` (path from `hooks/scripts/lib/agentic_loop_path.sh`), outside the repo, never committed.
- **PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment posted by `scripts/post_evals.sh` (marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> tier=<0|1|2> -->`) — see the invocation contract below.

## Invocation contract

Enforcement wiring is live: the merge gate lives in `scripts/merge.sh`, reading the PR-scope artifact `/coderails:post-evals` posts (via `scripts/post_evals.sh`); the loop-stop gate lives in `loop_state_guard` (`hooks/scripts/loop_state_guard.sh`), reading the loop-scope `evals.json` beside `progress.json`.

This skill is invoked at four points:

- **agentic-loop Phase 2.7** — loop scope, alongside `spec.md`/`plan.md`.
- **writing-plans**, once the plan has passed self-review and the stress-test pass — pr scope, frozen before implementation dispatch begins; the plan's actual final task only grades and posts via `/coderails:post-evals`.
- **systematic-debugging** — pr scope, frozen before the fix is implemented, when a debugging fix will carry a PR.
- **Directly by the user.**

A plan's or loop's per-work-unit eval refs travel in worker prompts the same way disposition travels under agentic-loop Phase 3's existing pattern: a ref recorded only in `progress.json` and absent from the worker's own prompt does not exist for that worker. Every worker prompt that owns a unit with an eval ref must carry that ref verbatim, not just a pointer to the loop state file.

## Verifier agent contract (agent-run evals)

For agent-run evals, a fresh sonnet subagent is spawned to grade. Its prompt contains: the `evals.json` content, artifact references (PR number, clone path, artifact path or local endpoint, deployed surface), and the confidence-label contract — and explicitly nothing else. It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion of the outcome — the same principle behind agentic-loop Phase 4b's clean-break gate (the author is the least able to see its own shims). The verifier returns per-eval status plus evidence; the orchestrator folds those statuses into `evals.json` — nothing more. Computing and stamping `result` is a separate, neutral step: `post_evals.sh` for pr scope, `post_evals.sh grade-loop` for loop scope. The orchestrator never writes `result` at either scope. Folding applies to fresh grader output only: an eval amended after a grader verdict goes back to a fresh grader, whose per-eval output is folded the same way, and the post-verdict amendment records who re-graded in a `regraded_by` field — `grade-loop` refuses to re-grade a post-verdict amendment that lacks it. `grade-loop` also stamps a `grading` object (`by`, a `checksum` over the per-eval statuses + result) that the loop-stop guard checks before accepting a GO/TIER0 verdict — honest boundary: the stamp catches accidental drift (a status edited after grading), not deliberate tampering. The stamp also records `amendments_at_grade`, which is what lets `grade-loop` detect a post-verdict amendment. The backstop's boundaries, stated plainly: it keys on amendment count growth after a grade-loop stamp. A status flipped with no accompanying amendment, an existing amendment edited or replaced in place, and a flip folded in before the first grade-loop run are all invisible to it, as is a hand-edited `amendments_at_grade` stamp (the stamp sits outside the checksum canon) — those cases are held by this rule and the Phase 13 audit alone. Amending means editing the graded file in place; regenerating the file sheds the stamp, and `grade-loop` treats remaining grade residue (`graded_at`/`result`) as the prior verdict, so a regenerated-but-residued file still refuses.
