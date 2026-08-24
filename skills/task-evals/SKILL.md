---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
effort: high
---

# Task Evals

How to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — before implementation starts, not after.

## Why this skill exists

coderails verifies everywhere, but always self-verifies. `superpowers:writing-plans` gives every task verify-criteria written by the same process that then implements against them. `agentic-loop` Phase 3/3a workers verify their own artifact; Phase 4b reviews code quality, not goal attainment; Phase 13 self-audits process counters, explicitly unscored. The `/merge` gate requires a SHA-bound review artifact — evidence that review happened, not that the task's goal state was reached. The one place coderails-adjacent work has had genuinely game-resistant acceptance evals is the hand-written public-readiness suite (E0–E10): negative controls, end-state assertions against fresh surfaces, independent GO/NO-GO gating, evals defined independently of task self-verification. This skill generalises that pattern. A model that wants to "pass" today writes its own verify-criteria, runs them itself, and grades itself — three conflicts of interest stacked. This skill exists to break that stack.

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

**The result is computed, not attested.** Do not hand-write the smoke evidence. Run `scripts/post_evals.sh smoke-run <evals.json>` immediately before freezing: it executes every scripted eval's `cmd` and `negative_control`, and writes the observed exit codes and output excerpts into a `smoke` object on each eval, overwriting whatever was there. `post_evals.sh validate-structure` (check 9) then refuses any pr-scope verification_level≥1 scripted eval lacking one.

The split matters. A checker that merely *reads* recorded exit codes is not enough, because the agent writes those numbers — and an agent freezing a command for a script it intends to create records the code it *expects* (`1`, "the assertion fails until I build it"), never having run the command. That is precisely how the real defect happened. This is rule 5 applied to smoke evidence: a neutral script computes it, the author never hand-writes it. `smoke-run` records without judging — it returns 0 even when what it observed is damning, because refusing is check 9's job.

**Gate-time re-execution (check 10).** Check 9 gates the *shape* of the recorded evidence, and the author writes those numbers — so a hand-written `smoke` object of plausible shape (`cmd_exit: 1`, control non-zero) for commands that were never run would pass check 9 on its own. Check 10 closes that: at pr scope, `validate-structure` itself EXECUTES every verification_level≥1 scripted eval's `cmd` and `negative_control` at the gate and judges only what it observes, never the typed numbers. It refuses on two distinct mechanisms: an empty or whitespace-only `cmd` or `negative_control` is refused before anything runs (blank means nothing to execute — and a whitespace-only cmd would otherwise exit 0 as a no-op and slip past the ungated cmd polarity); and an executed leg observed environmental (126/127/timeout/signal death) or a control observed exiting 0 is refused on the observation. It deliberately does NOT judge `cmd` polarity: freeze-before-build means a cmd that failed at freeze legitimately passes at merge, so only the build-independent facts — resolvability of both legs, and the control's defined-to-fail polarity — are recomputed. Same scope boundaries as checks 8/9: pr scope only, verification_level 0 and agent-run evals exempt, loop scope untouched. Commands run in the caller's cwd under the same 10s cap `smoke-run` uses — the cap kills the child's whole process group, so ordinary forking commands (bash scripts, test runners) are wall-clock bounded too; the one honest exception is a descendant that detaches into its own session (a daemonizing server), which escapes the group kill and can hold the gate open longer. The documented flow runs gate and smoke-run from the repo root, which is what keeps the two runs in agreement (a convention, not enforced by the script); running the gate from elsewhere can only fail closed, a false refusal rather than a false pass.

**Honest boundary, stated plainly.** What checks 9+10 close: a `cmd` or control that cannot execute at the gate (the never-created-script fabrication), and a control that does not actually fail — regardless of what the recorded smoke claims, because the gate recomputes both. What remains open: the freeze-time *content* exit code of `cmd` is build-dependent and genuinely cannot be recomputed at merge — an author who never ran the commands at freeze, but whose commands do resolve and whose control does fail at gate time, has typed a `cmd_exit` that is not mechanically distinguishable from a recorded one. That residue is exactly the polarity dimension; closing it needs a gated freeze step that stamps something unforgeable, or an external attestor outside the agent's trust domain (the integrity-review daemon pattern).

Check 9 refuses three outcomes, and deliberately permits a fourth:

- **`cmd` exited 126/127/142/≥128** — command not found, permission denied, timeout, or a signal death. The check never reached the artifact it claims to test. This is what catches a `cmd` naming a script that was only ever intended to exist.
- **`negative_control` exited 0** — a control that passes proves nothing. This is what catches a control whose file sat outside the tree being validated, or one that "removed" a tool still present on `PATH`.
- **`negative_control` exited non-zero for an environmental reason** — non-zero alone is not enough, because a control that errors out on its own tooling is just as vacuous as one that passes. The control must fail for a *content* reason.
- **Permitted: `cmd` exited non-zero for a content reason.** Freeze-before-build (check 8) means the feature is not built at freeze, so a failing `cmd` is the expected case. Check 9 keys on the *shape* of the outcome, never its polarity — requiring `cmd` to pass would contradict check 8 and block every honest freeze.

This is the pass/skip/fail distinction applied where it is load-bearing: "did not run" is separated from "ran and failed", so a skip can no longer read as compliance.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A frozen, blind-authored scripted check can be broken in itself — incapable of ever passing (false alarm) or ever failing (vacuous) — and the smoke-run above does not catch this, because it only proves the check *executes*, not that its verdict *tracks the input*. Real instance (loop 8b69e779): an awk formula that exited 1 unconditionally, so a genuine 39/39 pass and a genuine 18/40 fail produced identical exit codes and could never pass for any code state.

An eval may carry an optional `fixtures` object on top of the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

When present, `scripts/post_evals.sh validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula and requires opposite outcomes (good exits 0, bad exits non-zero) — rejecting the eval, by name, if both fixtures produce the same exit code (non-discriminating) or if the formula can't be reasonably derived from `cmd` (fail-closed, asks the author to supply `fixtures.formula` explicitly). The derivation splits on the last top-level pipe by text position, not shell syntax — a quoted pipe (e.g. inside an `awk` or `grep` pattern) forces `fixtures.formula` to be supplied explicitly, since the split would otherwise land inside the quoted string.

**Honest boundary, stated plainly:** this gate validates only checks that carry `fixtures`. Checks without `fixtures` are grandfathered — validated exactly as they were before this gate existed, with zero behaviour change. Adding `fixtures` to an eval is opt-in, never retroactive: freezing this gate does NOT retroactively validate any existing eval or evals.json that predates it, and an author who never adds `fixtures` gets no discrimination proof at all. And even where `fixtures` is present, a pass only proves the formula CAN discriminate between these two specific inputs — it proves nothing about whether the formula tests the RIGHT claim, whether `cmd` and `fixtures.formula` stay in sync after edits, or whether the fixtures themselves are representative. This gate closes the "never fails" class of defect; it is not a general correctness proof of the check.

## Verification level rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Verification level 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state. The exemption is still a written artifact — the gates accept a justified exemption, never an absence. Anything rule 6 names — something a human sees or interacts with (a UI, CLI output, a rendered artifact, a served endpoint) — **is** an outward surface for this predicate: a user-facing change is minimum verification_level 1 and carries rule 6's ≥1 P0 drive-the-artifact eval. (This widens only the verification_level-0 test: verification_level 2's outward predicate stays scoped to its own parenthetical list — publish, deploy, migration, data deletion, external send — so user-facing alone does not escalate past verification_level 1.)
- **Verification level 1 (standard):** anything above verification_level 0 that doesn't meet a verification_level-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Verification level 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

`verification_justification` is required at every verification_level, not only verification_level 0: at verification_level 0 it states why the exemption is legitimate; at verification_level 1/2 it names which predicate fired (e.g. "2 work-units, no irreversible surface" or "≥3 work-units"). A blank justification is refused by the writer (`post_evals.sh validate-structure`, check 2) at pr scope, and by the loop gates at loop scope — `loop_state_guard.sh`/`loop_stall_guard.sh` at completion and `loop_dispatch_guard.sh` at dispatch, all three via `als_read_loop_evals_result` — the pr-scope MERGE reader itself only parses the posted marker comment (result/verification_level, no justification field), so enforcement there is entirely writer-side, at post time.

Verification level fields remain planning metadata for selecting an appropriate eval set, but they are not authorization decisions. The root-owned daemon does not judge verification_level semantics; it mechanically attests the current SHA's review/eval evidence, provenance fields, policy paths, and bounded diff. Merge authorization depends on that `integrity-review` attestation, not on a semantic verification_level verdict.

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

**PR-scope path safety.** A pr-scope `artifact-path`/`merged-state` eval that reads or builds against a specific ref (the PR branch, a frozen base SHA) must never hardcode a shared, orchestrator-owned checkout path (e.g. the main working tree everyone else is also using) and assume its current contents match that ref — the shared checkout reflects whatever was last checked out there, not the ref under test, and drifts independently of the PR being graded. Use `git show <remote-ref>:<path>` for a blob read (no checkout needed), or a **persistent, create-if-absent** worktree of the exact ref (guarded by `git show-ref --verify --quiet` so a not-yet-existent branch fails loudly rather than vacuously passing) for anything that needs to build or run. Never destroy-and-recreate that worktree per invocation — it discards the build cache and can push a warm single-run check over a validator's timeout on every cold hit. Sanity-check: if the shared checkout's `HEAD` were on a totally different commit than the ref under test, would this eval still (correctly) fail? If not, it's observing the wrong thing.

## GO/NO-GO rule

GO requires all P0 evals to pass. P1 failures don't block the gate but must be listed unresolved in the artifact — they are visible debt, not silently dropped.

## Schema (schema_version 1)

```json
{
  "schema_version": 1,
  "scope": "pr | loop",
  "task_ref": "<branch/PR# for pr scope; session loop ordinal for loop scope>",
  "verification_level": 0,
  "verification_justification": "<required at every verification_level: verification_level 0 = why the exemption is legitimate; verification_level 1/2 = which verification_level predicate fired>",
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
      "smoke": {
        "_comment": "WRITTEN BY `post_evals.sh smoke-run`, never by hand — see 'Freeze-time smoke-run' above",
        "cmd_exit": "<observed exit code of cmd at freeze. Non-zero for a content reason is expected (freeze-before-build); 126/127/142/>=128 is refused>",
        "negative_control_exit": "<observed exit code of negative_control at freeze. Must be non-zero AND not environmental>",
        "cmd_output": "<excerpt of the raw output, captured by smoke-run>",
        "negative_control_output": "<excerpt of the raw output, captured by smoke-run>"
      },
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

`grading` (`{by, checksum, amendments_at_grade}`) is write-time provenance, absent at freeze and written only when `post_evals.sh grade-loop` grades a loop-scope file (see the Verifier agent contract below) — optional and additive; pr-scope files and every existing reader tolerate its absence. Adding it does not bump `schema_version` past 1. `grade-loop` also stamps top-level `.session_id`/`.loop_id`/`.revision` at the same write, read fresh from the sibling `progress.json` at grade time — same write-time-provenance, absent-at-freeze posture as `grading`, and likewise fails open (absent/unreadable `progress.json` leaves them unset) rather than blocking the grade.

`smoke` is required on scripted evals at pr scope (check 9) and carries no `schema_version` bump: it is additive, and loop-scope files — which check 9 does not gate — tolerate its absence exactly as before. Loop scope is excluded deliberately, matching check 8's boundary: loop-scope artifacts are gated by `loop_state_guard`, a separate surface with its own callers, so extending the smoke contract there is its own decision rather than a side effect of this one.

This file is the schema's only tracked copy — there is no separate design spec in the repo (verified: `git ls-files` matches nothing but this file). The enforcement components implement against this definition: `scripts/lib/eval-artifact.sh` (the marker/result SSOT), `scripts/post_evals.sh` (structural validation + result computation + `validate-discriminating`'s fixtures gate, invoked by `/coderails:post-evals`), and the `loop_state_guard` loop-scope gate (blocks loop completion at ≥1 work-units with no passing loop-scope `evals.json`).

## Where evals.json lives

- **Loop scope** → the loop-state dir beside `progress.json` (path from `hooks/scripts/lib/agentic_loop_path.sh`), outside the repo, never committed.
- **PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment posted by `scripts/post_evals.sh` (marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> verification_level=<0|1|2> -->`) — see the invocation contract below.

## Invocation contract

Enforcement wiring is live: the merge gate lives in `scripts/merge.sh`, reading the PR-scope artifact `/coderails:post-evals` posts (via `scripts/post_evals.sh`); the loop-stop gate lives in `loop_state_guard` (`hooks/scripts/loop_state_guard.sh`), reading the loop-scope `evals.json` beside `progress.json`.

This skill is invoked at four points:

- **agentic-loop Phase 2.7** — loop scope, alongside `spec.md`/`plan.md`.
- **superpowers:writing-plans**, once the plan has passed self-review and the stress-test pass — pr scope, frozen before implementation dispatch begins; the plan's actual final task only grades and posts via `/coderails:post-evals`.
- **superpowers:systematic-debugging** — pr scope, frozen before the fix is implemented, when a debugging fix will carry a PR.
- **Directly by the user.**

A plan's or loop's per-work-unit eval refs travel in worker prompts the same way disposition travels under agentic-loop Phase 3's existing pattern: a ref recorded only in `progress.json` and absent from the worker's own prompt does not exist for that worker. Every worker prompt that owns a unit with an eval ref must carry that ref verbatim, not just a pointer to the loop state file.

## Verifier agent contract (agent-run evals)

For agent-run evals, a fresh sonnet subagent is spawned to grade. Its prompt contains: the `evals.json` content, artifact references (PR number, clone path, artifact path or local endpoint, deployed surface), and the confidence-label contract — and explicitly nothing else. It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion of the outcome — the same principle behind agentic-loop Phase 4b's clean-break gate (the author is the least able to see its own shims). The verifier returns per-eval status plus evidence; the orchestrator folds those statuses into `evals.json` — nothing more. Computing and stamping `result` is a separate, neutral step: `post_evals.sh` for pr scope, `post_evals.sh grade-loop` for loop scope. The orchestrator never writes `result` at either scope. Folding applies to fresh grader output only: an eval amended after a grader verdict goes back to a fresh grader, whose per-eval output is folded the same way, and the post-verdict amendment records who re-graded in a `regraded_by` field — `grade-loop` refuses to re-grade a post-verdict amendment that lacks it. `grade-loop` also stamps a `grading` object (`by`, a `checksum` over the per-eval statuses + result) that the loop-stop guard checks before accepting a GO/VERIFICATION_LEVEL0 verdict — honest boundary: the stamp catches accidental drift (a status edited after grading), not deliberate tampering. The stamp also records `amendments_at_grade`, which is what lets `grade-loop` detect a post-verdict amendment. The backstop's boundaries, stated plainly: it keys on amendment count growth after a grade-loop stamp. A status flipped with no accompanying amendment, an existing amendment edited or replaced in place, and a flip folded in before the first grade-loop run are all invisible to it, as is a hand-edited `amendments_at_grade` stamp (the stamp sits outside the checksum canon) — those cases are held by this rule and the Phase 13 audit alone. Amending means editing the graded file in place; regenerating the file sheds the stamp, and `grade-loop` treats remaining grade residue (`graded_at`/`result`) as the prior verdict, so a regenerated-but-residued file still refuses.
