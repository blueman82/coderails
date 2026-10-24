---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
effort: high
---

# Task Evals

Define independent success evals for a non-trivial task before implementation starts. Freeze and grade them.

## Why this skill exists

Coderails has many checks, but much of its verification is self-directed. `superpowers:writing-plans` defines criteria in the same process that later implements the task. `agentic-loop` Phase 3/3a workers check their own work. Phase 4b reviews code quality, and Phase 13 checks process counts without scoring them. The `/merge` gate requires a SHA-bound review artifact. That shows a review took place; it does not show that the task's goal was reached. The hand-written public-readiness suite (E0–E10) uses stronger acceptance evals: negative controls, assertions against fresh end-state surfaces, and independent GO/NO-GO grading. This skill applies that pattern to other tasks. It separates the author of the criteria, the implementer, and the grader.

## Prerequisite: gather context before generating evals

Gather context before drafting an eval. Read the project wiki first. It may already state constraints, earlier decisions, and known problems. Read code for details the wiki does not cover. If the project has no wiki (`config.wiki_path` is null), read the codebase.

Dispatch this read to a sonnet agent. This keeps the orchestrator's context clear and makes the read a separate, auditable step, as in `agentic-loop` Phase 2. Ask the agent for concise findings instead of raw file dumps. Inside an agentic loop, reuse the orchestrator's Phase 2 pre-flight wiki findings. Do not repeat the read for each invocation.

This is a context-gathering prerequisite, not a verification step — do not conflate it with the gameability self-check or the six anti-gaming rules below.

## The six anti-gaming rules

Every eval must meet all six rules. If an eval fails one rule, it is invalid.

1. **Freeze-before-build.** Evals are generated and frozen (timestamp + base SHA) before implementation starts. Post-freeze edits are amendments with recorded reasons — visible, auditable, reported at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern). A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Run assertions against merged state, a fresh clone, a deployed artifact, or a locally built artifact that you drive directly (rule 6's PR-scope `artifact-path`). Do not use working-tree self-reports. A run of the artifact observes behavior; a self-report only describes the diff.
4. **Oracle independence.** An eval must not reuse the implementation's regex, fixture, or test as its oracle. Derive the eval from the task's goal state. For a loop, use **`authorising_prompt_raw` in `progress.json`**. This post-Phase-0 envelope is the one canonical string; do not choose between prompt versions. `spec.md` restates the loop's success criteria in Phase 2.7a, and `plan.md` restates them per task. Those files can add constraints and concrete surfaces to check. Their restatements cannot override the envelope's goal state. The `spec.md` copy is derived from `progress.json`; it is not a second authority.
5. **Grader independence.** A fresh subagent grades judgement evals. Give it only `evals.json` and artifact references, never the implementation conversation. A neutral assembly script computes `result`; the orchestrator never writes it by hand. Send an eval amended after a grader verdict to a fresh grader. The orchestrator never writes a per-eval `status` that reverses an existing verdict.
6. **Strongest surface.** If the goal names something a human sees or uses, at least one P0 eval must exercise it directly. Examples include a UI, CLI output, rendered artifact, and served endpoint. Drive the running artifact through a browser, CLI call, or HTTP request. A code grep of merged state is insufficient. Before a PR merges, use the locally run `artifact-path` surface; at loop scope, use the deployed surface. This is a writer-side rule. A script cannot detect whether a goal is user-facing, so generation and review must enforce it. For example, merged-state greps missed noise in a live streaming window; an in-browser eval across the stream found it.

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at`/`frozen_sha` on any eval, run this check against it once:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

This runs once per eval, immediately before freezing. An eval that fails the self-check is rewritten, not annotated or excused — there is no partial pass on this check.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freezing, run each scripted eval's `cmd` and
`negative_control` once. Read their raw output. The negative control proves a
check *can fail*. The smoke-run proves both commands *can execute*. A negative
control can work even when its paired `cmd` never runs. Run both this smoke-run
and the self-check above.

Look for signs that a command did not reach the artifact it claims to check.
Examples include a reporter-loading error instead of a test summary, a
module-resolution error (such as `ERR_MODULE_NOT_FOUND`) instead of an install
log, a stack trace instead of an assertion result, or a gate or policy denial
instead of the command's output. A non-zero exit in these cases does not prove
that the intended check ran.

If you find a broken `cmd` or `negative_control` before freezing, rewrite and
run it again. No amendment is needed yet. If you find it after `frozen_at` and
`frozen_sha` are stamped, use the amendment path. Record the reason and leave
the assertion unchanged. If that eval already has a grader verdict, request a
fresh grade under rule 5.

**The result is computed, not attested.** Do not hand-write smoke evidence. Run `scripts/post_evals.py smoke-run <evals.json>` immediately before freezing. It runs every scripted eval's `cmd` and `negative_control`. It then replaces each `smoke` object with observed exit codes and output excerpts. `post_evals.py validate-structure` (check 9) refuses a PR-scope scripted eval at verification level 1 or higher if that object is absent.

The split matters because an agent can write plausible exit codes without running a command. For example, it can record `1` for a script it plans to create and assume the assertion will fail before the build. That caused the real defect. Rule 5 applies to smoke evidence: a neutral script computes it. `smoke-run` records without judging, so it can return 0 even when the observed output shows a problem. Check 9 makes the refusal.

**Gate-time re-execution (check 10).** Check 9 checks the shape of recorded evidence. An author can write plausible numbers for commands that never ran, such as `cmd_exit: 1` and a non-zero control. At PR scope, check 10 makes `validate-structure` run every scripted eval's `cmd` and `negative_control` when verification level is 1 or higher. It judges the observed results, never the typed numbers.

Check 10 refuses a blank or whitespace-only command before it runs. It also refuses a command or control that fails for an environmental reason (126, 127, timeout, or signal death), or a control that exits 0. It does not judge `cmd` polarity: a command can fail before the build and pass at merge. The gate checks that both legs run and the control fails as defined.

Checks 8–10 apply at PR scope. Verification level 0 and agent-run evals are exempt; loop-scope evals are unchanged. Commands run in the caller's cwd with the same 10-second cap as `smoke-run`. The cap kills the child's process group. A daemonizing descendant can escape that group and hold the gate open longer. Run `smoke-run` and the gate from the repo root so their paths agree. The script does not enforce this cwd; running elsewhere can cause a false refusal.

**Evidence limit.** The local merge check runs scripted commands and controls again. It cannot prove the command's freeze-time result, because the build can change that result. An author could enter an unobserved freeze-time exit code that the merge gate cannot distinguish from a real one. The GitHub Actions integrity check reads the recorded results as data. It never runs a command from a PR comment.

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

When `fixtures` are present, `scripts/post_evals.py validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula. The good input must exit 0; the bad input must exit non-zero. It rejects the named eval if both exit codes match. If it cannot derive the formula from `cmd`, it fails closed and asks for `fixtures.formula`. Derivation splits at the last top-level pipe by text position, not by shell syntax. If an `awk` or `grep` pattern contains a quoted pipe, supply `fixtures.formula` explicitly; otherwise the split can land inside the quoted string.

**Limit:** this gate validates only checks that carry `fixtures`. Checks without them keep their earlier validation behavior. Adding `fixtures` is optional and never retroactive. Existing evals do not gain a discrimination proof unless their author adds fixtures.

Even with fixtures, a pass proves only that the formula distinguishes these two inputs. It does not prove that the formula tests the right claim, that `cmd` and `fixtures.formula` stay aligned after edits, or that the inputs represent the real case. The gate closes the "never fails" defect class. It is not a general correctness proof.

## Verification level rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Verification level 0 (exempt, justified):** All three conditions must hold: one work-unit, no outward or irreversible surface, and an existing test or verify criterion that covers the goal state. Record the exemption in an artifact; the gates accept a justified exemption, not an absent eval. A UI, CLI output, rendered artifact, or served endpoint is outward for this level-0 test. Such a user-facing change needs at least verification level 1 and one P0 eval that drives the artifact, as rule 6 requires. This does not by itself raise the change to level 2. Level 2 uses its own outward list: publish, deploy, migration, data deletion, and external send.
- **Verification level 1 (standard):** anything above verification_level 0 that doesn't meet a verification_level-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Verification level 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

`verification_justification` is required at every level. At level 0, it explains the exemption. At levels 1 and 2, it names the predicate that applies, such as "2 work-units, no irreversible surface" or "≥3 work-units".

For a PR, `post_evals.py validate-structure` (check 2) rejects a blank justification when the artifact is posted. For a loop, `loop_dispatch_guard.py` checks it at dispatch. `loop_state_guard.py` and `loop_stall_guard.py` check it at completion. All three use `loop_evals.read_loop_evals_result`. The PR-scope MERGE reader only parses the posted marker's result and verification level. It has no justification field, so the writer enforces this requirement at post time.

Verification level fields remain planning metadata for selecting an appropriate eval set. The trusted GitHub Actions workflow does not judge verification_level semantics. It checks the current SHA's review/eval evidence, provenance fields, policy paths, and bounded diff as data. Merge authorization depends on its `integrity-review` status after the server rule is active.

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
        "_comment": "WRITTEN BY `post_evals.py smoke-run`, never by hand — see 'Freeze-time smoke-run' above",
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
  "new_cases": [ { "id": "<must match a real .evals[].id>", "discovered_by": "<who/what found it>", "discovered_at": "<ISO8601>", "reason": "<why this case was missing from the frozen suite>", "regraded_by": "<fresh grader run>" } ],
  "result": null,
  "graded_at": null,
  "head_sha": "<SHA the grading ran against>"
}
```

`grading` (`{by, checksum, amendments_at_grade, suite_hash, integrity, chain_len, chain_head}`) is write-time provenance, absent at freeze and written only when `post_evals.py grade-loop` grades a loop-scope file (see the Verifier agent contract below) — optional and additive; pr-scope files and every existing reader tolerate its absence. Adding it does not bump `schema_version` past 1. `grade-loop` also stamps top-level `.session_id`/`.loop_id`/`.revision` at the same write, read fresh from the sibling `progress.json` at grade time, and FAILS CLOSED: a missing, unparseable, id-less or foreign `progress.json` refuses the grade (previously a missing file fell open).

`smoke` is required on scripted evals at pr scope (check 9) and carries no `schema_version` bump: it is additive, and loop-scope files — which check 9 does not gate — tolerate its absence exactly as before. Loop scope does not require `smoke`, but `grade-loop` executes each scripted `negative_control` (see below).

**Loop-scope controls are executed (decision).** `grade-loop` runs every scripted `negative_control` of a verification_level>=1 loop suite (caller cwd, 10s cap): exit 0 refuses `control_passes`, an environmental exit (126/127/>=128) refuses `control_env`, any other non-zero exit is accepted. `grade-loop` also re-executes each scripted `cmd` (same cwd and cap): a recorded `pass` whose `cmd` exits non-zero refuses `pass_exit_nonzero`, an environmental exit refuses `cmd_env`. The loop-stop guard stays a time-bounded presence-and-hash check; it executes nothing. `grade-loop` also fails closed on identity: a missing `progress.json` (`progress_missing`), one that does not parse or lacks `session_id`/`loop_id` (`progress_unparseable`), or a suite already stamped with different ids (`progress_foreign`) refuses; there is no bypass flag, restore `progress.json` for an archived suite. `schema_version` 3 is not required (schema 2 grades, traced `legacy_progress_schema`).

**Tamper-evidence (Phase F).** `post_evals.py smoke-run` also stamps top-level `frozen_hash`: sha256 of the oracle (per-eval `id, priority, mode, cmd, negative_control, fixtures, expected, assert`, plus `task_ref, scope, verification_level`). `status, smoke, result, graded_at, grading, amendments, amendment_chain, new_cases` are excluded because they change legitimately.

`smoke-run` stamps only a never-frozen, never-graded suite; on an already-frozen suite it first verifies the oracle and refuses `suite_hash_mismatch` if it was edited since (record the edit with `amend`, then re-run).

Editing the oracle after freeze is done by editing the file and then running `post_evals.py amend <evals.json> <eval_id> <reason> <actor> [regraded_by]`, which appends to `amendment_chain[]` (`seq, eval, reason, ts, actor, prev_hash, suite_hash_after, hash`; genesis `prev_hash` is `frozen_hash`) and to the legacy `amendments[]`.

`grade-loop` and the loop completion reader refuse with a printed `reason=<code>`: `suite_hash_mismatch`, `chain_broken`, `chain_truncated`, `integrity_stripped` (`frozen_hash` deleted from a suite graded with one). The completion reader returns `TAMPERED:<code>` and the Stop-hook message prints that code; the trace row is in `eval_trace.jsonl` beside `evals.json`.

`grading` additionally records `suite_hash`, `integrity`, `chain_len`, `chain_head`.

Honest trust boundary: this is tamper-EVIDENT, not adversary-proof. Signing (next paragraph) closes this only against actors without the key; an actor with the key who rewrites the oracle, the chain and the grading stamp together (or truncates and regrades) is not caught, and transcript forgery is out of scope (`skills/agentic-loop/loop-state.md`).

Script files a `cmd` references are not hashed (at PR scope they are bound by `head_sha`; at loop scope they are not bound).

A suite with no `frozen_hash` is grandfathered as `legacy_unhashed`: it still grades, `grading.integrity` says so, `reason=legacy_unhashed` is printed and traced, never a silent pass at grade time.

Residual, stated plainly: deleting `frozen_hash` together with the `grading` tombstones (`integrity`, `suite_hash`, `chain_*`) turns a graded suite into an indistinguishable legacy one, and deleting it before the first grade lets `smoke-run` re-freeze; both need an anchor outside the same-user key (a ledger); signing does not provide one, so the other evidence is the non-authoritative trace rows.

**Signing (Phase F, item 4).** `smoke-run` and `amend` also write a suite-level `signature` ({signer, payload, sig}; `ssh-keygen -Y sign`, namespace `coderails-evals`, key in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`, mode 0600, created on first sign) over `{frozen_hash, chain_head, chain_len, loop_id, session_id}`; `grade-loop` re-signs after stamping the ids and sets `grading.signed`. Readers refuse `signature_invalid`, `signer_unknown`, `signature_missing` (stripped after `grading.signed` or under `evals.require_signatures: true`), `key_perms`; unsigned frozen suites are `legacy_unsigned` and a verifier without ssh-keygen/allowed_signers is `key_missing` (both loud, non-blocking unless required). Trust boundary: detects edits made without the key and lets a party holding only the public key verify; it does NOT stop a same-user agent, which can read the 0600 key and re-sign, and it does NOT detect a rollback to an earlier validly-signed state (only `grading.chain_len` partially guards). Runbook: `docs/graph-alignment-measurement.md`.

**Gate rules added.** At the gate (`verify_execution`, via `validate-structure` and `smoke-verify`) an eval recorded `status: pass` whose `cmd` exits non-zero is refused `pass_exit_nonzero`; freeze-time `smoke` still accepts a non-zero (TDD-red) `cmd` exit. When `fixtures` are present, `fixtures.formula` must be the literal tail of `cmd` (`fixture_formula_not_in_cmd`), so fixtures run against the real checker text.

`new_cases[]` covers a third gap distinct from the other two amendment paths: a later independent review discovers the frozen suite is missing a case ENTIRELY — no eval was ever written for it because nobody anticipated it at freeze time. This differs from `amendments[]` (which edits an EXISTING eval id) and from `withdrawn_proofs` (a proof that ran and legitimately failed): here nothing was ever graded for the case until it was folded into an existing eval's `id`. Each `new_cases[]` entry's `id` must equal a real `.evals[].id` in the same file — `post_evals.py validate-structure` (check 11) refuses any entry whose `id` matches no `.evals[].id`, same posture as the other structural checks (non-zero exit, printed reason, no stamp written). Absent or empty `new_cases[]` is a no-op — most PRs never discover an uncovered case, and check 11 does not regress those files.

This file is the schema's only tracked copy — there is no separate design spec in the repo (verified: `git ls-files` matches nothing but this file). The enforcement components implement against this definition: `scripts/lib/eval_artifact.py` (the marker/result SSOT), `scripts/post_evals.py` (structural validation + result computation + `validate-discriminating`'s fixtures gate, invoked by `/coderails:post-evals`), and the `loop_state_guard` loop-scope gate (blocks loop completion at ≥1 work-units with no passing loop-scope `evals.json`).

## Where evals.json lives

- **Loop scope** → the loop-state dir beside `progress.json` (path from `hooks/scripts/lib/agentic_loop_path.py`), outside the repo, never committed.
- **PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment posted by `scripts/post_evals.py` (marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> verification_level=<0|1|2> -->`) — see the invocation contract below.

## Invocation contract

Enforcement wiring is live: the merge gate lives in `scripts/merge.py`, reading the PR-scope artifact `/coderails:post-evals` posts (via `scripts/post_evals.py`); the loop-stop gate lives in `loop_state_guard` (`hooks/scripts/loop_state_guard.py`), reading the loop-scope `evals.json` beside `progress.json`.

This skill is invoked at four points:

- **agentic-loop Phase 2.7** — loop scope, alongside `spec.md`/`plan.md`.
- **superpowers:writing-plans**, once the plan has passed self-review and the stress-test pass — pr scope, frozen before implementation dispatch begins; the plan's actual final task only grades and posts via `/coderails:post-evals`.
- **superpowers:systematic-debugging** — pr scope, frozen before the fix is implemented, when a debugging fix will carry a PR.
- **Directly by the user.**

A plan's or loop's per-work-unit eval refs travel in worker prompts the same way disposition travels under agentic-loop Phase 3's existing pattern: a ref recorded only in `progress.json` and absent from the worker's own prompt does not exist for that worker. Every worker prompt that owns a unit with an eval ref must carry that ref verbatim, not just a pointer to the loop state file.

## Verifier agent contract (agent-run evals)

For agent-run evals, spawn a fresh sonnet subagent. Give it only:

- The `evals.json` content.
- Artifact references: the PR number, clone path, artifact path or local
  endpoint, and deployed surface.
- The confidence-label contract.

Do not give it the implementation conversation, the implementer's summary,
or the orchestrator's verdict. The author can miss its own compatibility
shims, as explained in agentic-loop Phase 4b. The verifier returns one status
and evidence for each eval. The orchestrator folds only those statuses into
`evals.json`.

Compute and stamp `result` in a separate neutral step. Use `post_evals.py`
for PR scope or `post_evals.py grade-loop` for loop scope. The orchestrator
must not write `result` at either scope.

Fold only fresh grader output. After an eval amendment, send the changed
eval to a fresh grader. Fold its new per-eval result. A post-verdict
amendment records the grader in `regraded_by`. `grade-loop` refuses a
post-verdict amendment without that field.

For loop scope, `grade-loop` stamps a `grading` object. It records `by`, a
checksum over per-eval statuses and `result`, and `amendments_at_grade`.
The loop Stop guard uses this stamp to accept `GO` or
`VERIFICATION_LEVEL0`. The checksum catches an accidental status edit after
grading. It does not protect against deliberate tampering.

`grade-loop` compares the amendment count with `amendments_at_grade` to
detect a post-verdict amendment. It cannot detect a status change without a
new amendment. It also cannot detect an old amendment edited in place, a
change folded before the first `grade-loop` run, or a hand edit to
`amendments_at_grade`. That field is outside the checksum. This rule and
the Phase 13 audit hold those cases.

Amend the graded file in place. Regenerating the file removes the stamp.
If `graded_at` or `result` remains, `grade-loop` treats it as a prior
verdict and still refuses a missing `regraded_by` field.
