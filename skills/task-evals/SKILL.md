---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
effort: high
---

# Task Evals

Before implementation, freeze a set of checks that measure if the task succeeded. Grade those checks independently of the implementation.

## Why this skill exists

Coderails checks work during the loop. `superpowers:writing-plans` gives each task checks from the same agent that does the work. In Phases 3 and 3a, workers check their own artifacts. Phase 4b checks code quality. Phase 13 reports loop counters without a score.

The `/merge` gate checks for a SHA-bound artifact from the reviewer. That artifact records the reviewer’s result. It does not show the task met its goal.

The hand-written public-readiness suite (E0–E10) used negative controls and checked end results on new surfaces. It graded GO or NO-GO independently of the task’s own checks. A model can mark its own work "pass" when it writes, runs, and grades its own checks. Write, run, and grade the evals without relying on the worker’s own checks.

## Prerequisite: gather context before generating evals

Before drafting an eval, read the project wiki for goal constraints, prior decisions, and known problems. Read source for topics the wiki does not include. If `config.wiki_path` is null, use source for all target context.

Delegate this read to a sonnet agent, as in the Phase 2 pre-flight. The agent gives a short summary of the results. This makes the context check easy to audit. Do not copy file contents into the orchestrator context. If the Phase 2 wiki read is available, use it for this prerequisite.

This read supplies context. Run the gameability check and apply the six rules independently.

## The six anti-gaming rules

An eval must satisfy all six rules.

1. **Freeze-before-build.** Make and freeze the evals with their timestamp and base SHA before implementation starts. Record why each edit after freeze was necessary. Include the edits in the report at loop end.
2. **Negative controls.** For each scripted eval, include a command that shows the check can give a negative result (E0 pattern). Check the control before you trust a positive test result.
3. **End-state surfaces.** Run assertions against a merged ref, new clone, or deployed artifact. At PR scope, use a locally built artifact as in rule 6’s `artifact-path`. Run the local artifact directly. Do not use a working-tree self-report or quote the diff as the result.
4. **Oracle independence.** Use the task goal to derive the assertion. Do not share the implementation’s oracle, such as its regex, fixture, or test. At loop scope, use **`authorising_prompt_raw` from `progress.json`** as the canonical post-Phase-0 goal. Use `spec.md` and `plan.md` for constraints and testable surfaces. The criteria in those files do not override the envelope’s goal.
5. **Grader independence.** Use a new subagent for judgment evals. Give it only `evals.json` and pointers to the artifacts. Do not give it the implementation conversation. A neutral script calculates `result`. Do not write it by hand. If an eval changes after a verdict, send it to a new grader. Do not write a `status` that flips a prior verdict.
6. **Strongest surface.** If the goal includes a UI, CLI output, rendered artifact, or served endpoint, test that surface directly. Use one or more P0 evals. For example, use a browser, CLI invocation, or HTTP call. A source search alone cannot satisfy this rule. Before merge, use the local artifact as `artifact-path`. At loop scope, use the deployed surface. The author and reviewer check this rule because a script cannot identify all "user-facing" work.

   In the run-output noise-strip loop, checks on merged code succeeded while the live stream leaked output. Only a browser eval across the streaming lifecycle found the problem.

## Gameability self-check (mandatory before freezing)

Before you set `frozen_at` and `frozen_sha`, apply this question to each eval:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

Do this one time for each eval, immediately before freeze. If it does not satisfy the check, rewrite it. Do not use a note or waiver as approval.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freeze, run each scripted `cmd` and its `negative_control`. Read their raw output. The control shows that the check can give a negative result. The smoke-run checks that each command can run. A working control does not show that its paired `cmd` can run. Do the gameability check and smoke-run as two steps.

For example, a reporter may give a loading error without a test summary. A module may give `ERR_MODULE_NOT_FOUND` without an install log. The test can stop and print the call stack before the assertion. A policy may deny the command before it prints its own output. The command can exit nonzero without a check of the artifact. Do not count this as a content "fail."

Before freeze, correct a broken `cmd` or `negative_control` and run it again. There is no freeze record to update. After the freeze sets `frozen_at` and `frozen_sha`, use `amend`. Record why you changed the command and keep the assertion. If a grader gave a verdict, get a new grade as in rule 5.

**Use the measured smoke result.** Run `scripts/post_evals.py smoke-run <evals.json>` immediately before freeze. It runs each scripted `cmd` and `negative_control`. It replaces each eval’s `smoke` object with measured exit codes and output excerpts. Do not write this object by hand. Check 9 in `post_evals.py validate-structure` refuses a PR-scope scripted eval at verification_level 1 or above without that object.

A reader of recorded exit codes alone cannot know if the command ran. An author can write the expected exit code, such as `1` and "the assertion fails until I build it". This happened before. The `smoke-run` command records what it sees and exits 0. Check 9 decides if the records qualify.

**Check 10 reruns commands at the gate.** Check 9 checks the recorded data’s shape. For example, a hand-written `smoke` with `cmd_exit: 1` and a nonzero control code can satisfy that check without a run. At PR scope, `validate-structure` also runs the scripted `cmd` and `negative_control` at verification_level 1 or above. It checks the results from that run.

If a `cmd` or `negative_control` is empty or has only whitespace, the gate refuses it before execution. A blank command can exit 0 without a check. The gate refuses an environment error from the command or the control: 126, 127, timeout, or signal termination. It also refuses a control that exits 0.

Check 10 does not use the sign of the `cmd` result to judge the feature. A command can give a negative result before build and succeed at merge. It checks only that the commands can run and the control exits nonzero for a content cause. Like checks 8 and 9, it applies only at PR scope, with exemptions for verification_level 0 and agent-run evals.

The gate and smoke-run use the caller’s cwd and the same 10s limit. At the limit, the runner kills all members of the child's operating system group. This includes ordinary children of shell scripts and test runners. A descendant that starts a new session can outlive the group kill and hold the gate open longer.

Run the gate and smoke-run from the repo root. The script does not check this convention. A run from a different directory can give an incorrect refusal if the commands cannot run there.

**Limit of the check.** The local merge gate runs the command and control again. It refuses a command it cannot run or a control that exits 0. It cannot show what the command gave at freeze. The GitHub workflow reads the recorded results as data. It does not run a command from a PR comment.

Check 9 uses these results:

- **`cmd` exits 126, 127, 142, or 128 and above.** The command cannot run, exceeds its time limit, or ends on a signal. The check refuses it. This can catch a command for a script the author planned to write.
- **`negative_control` exits 0.** The check refuses it. For example, the control’s file can be external to the checked tree. The "removed" tool can be on `PATH`.
- **`negative_control` exits nonzero for an environment cause.** The check refuses it. The control must run and give a negative result for the expected content cause.
- **`cmd` exits nonzero for a content cause.** The check permits this. At freeze the feature may not be built. Check 8 requires this timing.

Record "did not run" and "ran and failed" as different results. A skipped check does not show compliance.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A scripted check can give the same result for all inputs. The smoke run only shows that the command runs.
In loop `8b69e779`, an `awk` formula always gave exit code 1.
It gave the same result for a correct 39/39 pass and an 18/40 fail.

A scripted eval can include this optional `fixtures` object.

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

`scripts/post_evals.py validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula.
The good input must exit 0. The bad input must exit with a nonzero code.
The command names and rejects the eval if the exit codes differ from the required results.

It also rejects an eval if it cannot get the formula from `cmd`. Supply `fixtures.formula` if necessary.
The check uses the text after the last top-level pipe. It does not parse shell syntax.
Specify `fixtures.formula` if a quoted pattern contains a pipe.

The gate applies only to evals with `fixtures`. It does not apply to earlier suites unless you add fixtures.
A positive result proves that the formula can distinguish the two inputs. This detects a "never fails" check for those inputs.
Check independently that the formula tests the claim, matches `cmd` after edits, and uses samples that reflect actual inputs.

## Verification level rules (self-exemption defence)

Use the conditions below. This uses the same approach as the Phase 2.6 question about retirement "what named thing does this remove?"

- **Verification level 0.** Use for one work unit with no outward or irreversible surface. An existing test or verification check must check the required condition. Record the exemption in the suite. The gate requires a written exemption. A UI, CLI output, rendered artifact, or served endpoint is an outward surface in rule 6. These changes require a minimum of level 1 and one direct P0 test of the artifact. Only the listed outward operations at level 2 make a user-facing change reach level 2 on its own.
- **Verification level 1 (standard).** Use when level 0 does not apply and the change meets no level 2 condition. Write 3–5 tests of the required end condition. Include one or more negative controls. Use P0 and P1.
- **Verification level 2 (full suite).** Use for three or more work units or an irreversible or outward operation. The operations are publish, deploy, migrate, delete data, and send externally. Include checks before and after the change where applicable. Give the GO/NO-GO rule in the artifact.

Supply `verification_justification` at each level. Give the basis for the exemption at level 0.
At levels 1 and 2, give the condition that applies. Examples are "2 work-units, no irreversible surface" and "≥3 work-units".
`post_evals.py validate-structure` check 2 rejects a blank `verification_justification` at PR scope.

At loop scope, `loop_state_guard.py` and `loop_stall_guard.py` check it at the end.
`loop_dispatch_guard.py` checks it at dispatch. All three use `loop_evals.read_loop_evals`.
The PR merge reader gets the result and level from the marker. The PR writer alone checks `verification_justification` before it posts.

**Minimum level.** `policy/surface_policy.json` gives these path groups.

- Irreversible paths include `install.py`, `uninstall.py`, `launchd/`, and `scripts/integrity-gate/`.
  They also include `scripts/installer/`, `.github/workflows/`, and the two `hooks.json` files.
- Outward paths include `commands/`, `skills/`, `hooks/`, `scripts/`, and `agents/`.
  They also include `packages/codex/`, `policy/`, and `capabilities/`.
- The paths for docs and tests have no outward or irreversible class.

`scripts/lib/eval_level.py` uses the PR diff to calculate the minimum.
Level 0 requires one work unit and no outward or irreversible path.
An outward path or two units requires a minimum of level 1.
An irreversible path or the unit count in `level_2_work_units` (3) requires level 2.
The declared `facts{work_units,surfaces}` give a minimum. The check uses the `progress.json` unit count when `post_evals.py post --progress` finds the file.

`post_evals.py post`, `merge.py`, the Claude direct merge path, and the Codex hook use the live diff.
They refuse a level below the minimum with `level_below_derived`.
The PR gate also runs `verify_suite`.
It reports `suite_hash_mismatch` for an oracle edit after `smoke-run` with no `amend`.
A level 1 or 2 suite without `frozen_hash` gets `not_frozen` or `integrity_stripped`.

The checker treats a `frozen_sha` that is not an ancestor of the branch base as late. Supply the required `reason`.
The second line of the body (`coderails-eval-facts v1`) records `late_freeze=1`.
A line that disagrees with the computed value causes `late_freeze_unstamped`.

The diff cannot give the work-unit count.
The gate counts one unit without `--progress` or a declared minimum. An agent with the same user access can supply a smaller count.
Use levels above the floor to select the required eval set.

The trusted GitHub workflow checks the current SHA's `coderails-review-summary` and `coderails-eval-summary` records, provenance fields, policy paths, and bounded diff.
Merge requires that `integrity-review` attestation. The workflow does not judge the verification level selection.

**Freeze provenance.** `smoke-run` sets `integrity_version: 2` on each new level 1 or 2 suite.
Its frozen hash and signature bind `frozen_sha` and `frozen_at`.

Version 1 suites keep their initial hash and signature.
Their freeze time remains unverifiable if the SHA is an ancestor of the branch base.
To post a version 1 suite, keep the source and use `post_evals.py amend` on a copy.
Use this `reason` as written `frozen_sha <40-hex SHA> frozen_at <ISO8601> timing=unverifiable`.

For a late version 2 freeze, use `timing=late` in the signed `reason`. If the suite has no freeze, use `timing=unverifiable`.
Grade the copy again before you post it. The PR writer and local merge checks require a trusted signer and check the branch base.
The GitHub workflow checks the signature bytes and versioned hash.
It has no trusted signer list or branch ancestry proof.

## Eval anatomy

Each eval object in the `evals` array has these fields.

- **ID.** Use a short identifier such as `E1`.
- **`priority`.** A P0 issue blocks the gate. Correct P1 issues before you announce the result.
- **Mode.** Use `scripted` for a deterministic command or `agent-run` for a new verifier agent's judgment.
- **Surface.** Use `merged-state | fresh-clone | artifact-path | deployed`. Use `artifact-path` for a local file, CLI invocation, or served endpoint built or run before merge. Use `deployed` for the endpoint on the live instance after merge.
- **Assertion.** Give the required result on one line.
- **Command or verifier instruction.** Give the command or the instructions for the verifier agent.
- **Negative control.** A scripted eval requires a command that shows the check can give a negative result.
- **`expected`.** Give the result the check must show.

**PR-scope path safety.** Use the specified PR branch or frozen base SHA for each `artifact-path` or `merged-state` check that needs it.
A shared checkout can change independently of that ref. Do not use its current contents.
Use `git show <remote-ref>:<path>` to read a blob.

For a build or run, use a worktree at the specified ref. Make it only if there is no such worktree.
Use `git show-ref --verify --quiet` to report an error for a missing branch.
Keep the worktree between runs. A new worktree loses the build cache and can cause each check to time out.

Check that a different `HEAD` in the shared checkout cannot change the result.

## GO/NO-GO rule

GO requires a positive result for each P0 eval. P1 issues do not block the gate. List open P1 issues in the artifact.

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

`post_evals.py grade-loop` writes `grading` when it grades a loop suite.
It records `{by, checksum, amendments_at_grade, suite_hash, integrity, chain_len, chain_head}`.
A frozen, ungraded suite has no `grading`. PR files and existing readers accept files without it.
The field uses the same `schema_version` of 1.

The grader also reads `.session_id`, `.loop_id`, and `.revision` from the sibling `progress.json` and writes them at the top level.
It refuses the grade for a missing or unreadable file, missing IDs, or IDs from a different loop.

Check 9 requires `smoke` for scripted PR evals. This uses the same `schema_version`.
At loop scope, `smoke` is optional and `grade-loop` runs the scripted negative controls.

**Loop-scope controls.** For a loop suite at level 1 or higher, `grade-loop` runs each scripted `negative_control`.
It uses the caller's cwd and a 10s limit. Exit 0 gives `control_passes`.

Exit 126, 127, or ≥128 gives `control_env`. The grader accepts the other nonzero exit codes.
It also runs each scripted `cmd` with the same cwd and limit.
An environment error gives `cmd_env`. A nonzero exit for a recorded `pass` gives `pass_exit_nonzero`.

The loop Stop guard checks for the file and verifies hashes with a time limit. It runs no eval commands.
`grade-loop` refuses with `progress_missing` if there is no `progress.json`.
It reports `progress_unparseable` if it cannot read the JSON or find `session_id` and `loop_id`.
It reports `progress_foreign` if the suite has different IDs from a prior grade.

For an archived suite, restore its `progress.json`. There is no bypass flag.
The grader accepts `schema_version` 2 and logs `legacy_progress_schema`.

**Freeze hash (Phase F).** `post_evals.py smoke-run` writes `frozen_hash`, a SHA-256 hash of the oracle.
The hash covers `id, priority, mode, cmd, negative_control, fixtures, expected, assert` for each eval and `task_ref, scope, verification_level` for the suite.
The changeable fields `status, smoke, result, graded_at, grading, amendments, amendment_chain, new_cases` are not part of this hash.

`smoke-run` writes the first hash only for a suite with no prior freeze or grade.
For a frozen suite it checks the oracle first. An unrecorded edit gives `suite_hash_mismatch`.

To edit the oracle after freeze, edit the file and run `post_evals.py amend <evals.json> <eval_id> <reason> <actor> [regraded_by]`.
It adds an entry to `amendment_chain[]` and to the older `amendments[]`.
The chain entry contains `seq, eval, reason, ts, actor, prev_hash, suite_hash_after, hash`.
The first `prev_hash` is `frozen_hash`. Run `smoke-run` again after you record the edit.

`grade-loop` and the reader at the end of the loop report `reason=<code>` with `suite_hash_mismatch`, `chain_broken`, `chain_truncated`, or `integrity_stripped`.
The last code applies if the suite has no `frozen_hash` after a grade that recorded one.
The reader gives `TAMPERED:<code>` and the Stop hook prints it.
The record is in `eval_trace.jsonl` next to `evals.json`.
`grading` also records `suite_hash`, `integrity`, `chain_len`, and `chain_head`.

The signature protects against edits by someone without the signing key. A user with that key can change and sign the records again.
See `skills/agentic-loop/loop-state.md` for the boundary on forged transcripts.
The suite hash excludes the script files that `cmd` calls. PR scope binds them to `head_sha`. Loop scope has no such binding.

The grader accepts suites with no freeze record as `legacy_unhashed` and records it in `grading.integrity`.
It prints and logs `reason=legacy_unhashed`.
Without `frozen_hash` and the grade's `integrity`, `suite_hash`, and `chain_*` fields, the reader cannot distinguish a graded suite from an older suite.
Without the freeze hash before the first grade, `smoke-run` can freeze it again.
Detection in these conditions needs a ledger that the signing user cannot control. The available log records are advisory.

**Signing (Phase F, item 4).** `smoke-run` and `amend` write a suite `signature` with `signer, payload, sig`.
They use `ssh-keygen -Y sign` in the `coderails-evals` namespace.
On the first signature, the writer makes the key in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys` with mode 0600.
The signature binds `frozen_hash, chain_head, chain_len, loop_id, session_id`.
`grade-loop` signs again after it adds the IDs and sets `grading.signed`.

Readers refuse `signature_invalid`, `signer_unknown`, `signature_missing`, and `key_perms`.
The `signature_missing` refusal applies with `grading.signed` or `evals.require_signatures: true`.
A frozen suite without a signature gives `legacy_unsigned`.
A verifier without `ssh-keygen` or `allowed_signers` gives `key_missing`.
The reader reports these conditions and blocks only if a signature is mandatory.

A verifier with only the public key can check the signature. An agent with the same user access can read the key and sign again.
The reader can accept an earlier copy with a correct signature. Only `grading.chain_len` checks part of this condition.
See `docs/graph-alignment-measurement.md`.

**Gate rules added.** `validate-structure` and `smoke-verify` call `verify_execution`.
A recorded `status: pass` with a nonzero `cmd` exit gives `pass_exit_nonzero`.
Freeze-time `smoke` accepts a nonzero `cmd` exit for a test that has no positive result.
If the eval has `fixtures`, `fixtures.formula` must be the text at the end of `cmd`.
A mismatch gives `fixture_formula_not_in_cmd`.

Use `new_cases[]` if a different agent finds a condition that the frozen suite did not test.
Add that condition to an existing eval and record its ID. There was no grade for the new condition before that edit.
Use `amendments[]` for edits to a condition that an eval tests. Use `withdrawn_proofs` for a proof with a correct negative result.

Each `new_cases[]` entry's `id` must be one of the `.evals[].id` values in the same file.
`post_evals.py validate-structure` check 11 refuses unknown IDs. It exits nonzero, prints the cause, and writes no stamp.
It accepts a missing or empty `new_cases[]`.

This section gives the schema for Claude Code. The Codex copy is in `packages/codex/skills/task-evals/SKILL.md`.
(verified: `git ls-files '*task-evals/SKILL.md'` and the schema in each file)
`scripts/lib/eval_artifact.py` defines the marker and result.
`scripts/post_evals.py` checks the structure and fixtures and computes the result for `/coderails:post-evals`.
`loop_state_guard` blocks the end of loops with one or more units and no loop suite with a passing grade.

## Where evals.json lives

- **Loop scope.** Keep the file next to `progress.json` in the loop-state directory. Get the path from `hooks/scripts/lib/agentic_loop_path.py`. Keep the file in a directory external to the repo.
- **PR scope.** Use the local file as a draft. `scripts/post_evals.py` posts the durable PR comment for the head SHA. Its marker is `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> verification_level=<0|1|2> -->`.

## Invocation contract

`scripts/merge.py` reads the PR comment that `/coderails:post-evals` posts through `scripts/post_evals.py`.
`loop_state_guard` (`hooks/scripts/loop_state_guard.py`) reads the loop `evals.json` next to `progress.json`.

Use this skill at these four points.

- **agentic-loop Phase 2.7.** Use loop scope next to `spec.md` and `plan.md`.
- **superpowers:writing-plans.** Use PR scope after the plan passes self-review and the stress test. Freeze before the first worker starts. The last plan task only grades and posts through `/coderails:post-evals`.
- **superpowers:systematic-debugging.** When the correction will have a PR, use PR scope. Freeze before you make the correction.
- **Directly by the user.**

Copy each work-unit eval ref into that worker's prompt as written. Follow the same Phase 3 pattern as for the work unit's `disposition`.
The worker must have the ref in its prompt. A ref or pointer in `progress.json` is not sufficient.

## Verifier agent contract (agent-run evals)

Start a new Sonnet agent to grade the evals.
Give it only the contents of `evals.json`, the artifact refs, and the confidence-label contract.
Include the PR number, clone path, artifact path or local endpoint, or deployed surface as applicable.
Keep the implementation conversation, the worker's summary, and the orchestrator's judgment out of its prompt.
This applies the independence rule of the Phase 4b clean-break gate.

The verifier gives the status and its basis for each eval. Copy only the verifier's status for each eval into `evals.json`.
Use `post_evals.py` at PR scope and `post_evals.py grade-loop` at loop scope to calculate and stamp `result`.
The orchestrator must let the script write `result` at each scope.

For an eval edit after a verdict, get a new verifier and use its status in the file.
Record who graded again in `regraded_by`. `grade-loop` refuses an edit after a verdict without that field.

It adds `grading.by` and a `grading.checksum` for eval statuses and result.
The loop Stop guard checks this data before it accepts `GO` or `VERIFICATION_LEVEL0`.
The checksum detects accidental edits to a status after a grade. A deliberate edit can evade it.

`grade-loop` uses `amendments_at_grade` to find an increase in the number of recorded edits since the grade.
It cannot detect a status edit without an entry, a change to an existing entry, or a status edit before the first grade.
It cannot detect an edit to `amendments_at_grade` because the checksum does not include that field.
This rule and the Phase 13 audit apply to those conditions.

Edit the same graded file. A new file can have no grading stamp.
If the file keeps `graded_at` or `result`, `grade-loop` treats that as a prior verdict and refuses the edit.
