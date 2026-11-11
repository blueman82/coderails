---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
---

# Task Evals

Before implementation starts, make and freeze success evals. Give them an oracle different from the implementation's. Grade them after the work.

## Why this skill exists

The same procedure can write, run, and grade ordinary implementation checks.
`$coderails-codex:merge` needs a SHA-bound inspection record. That record alone does not prove that the task achieved its goal.
This skill checks the goal apart from the implementation. It uses negative controls and grading by a different agent.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Each
helper command below uses the package-local
`$SKILL_DIR/../../scripts/post_evals.py`.

## Prerequisite: gather context before generating evals

Before you draft an eval, read the project wiki for target context. Find the rules, constraints, decisions, and known problems that apply to the goal.
Read the codebase for topics the wiki does not include. If the project has no wiki (`config.wiki_path` is null), read the codebase for all target context.

Start a new Codex subagent with `spawn_agent` to read these sources. Tell it to give a short summary without full file contents.
In a native agentic loop, use an existing pre-flight wiki read if available.

Use this prerequisite to get context. Apply the self-check and the six rules below after you have the context.

## The six anti-gaming rules

An eval must satisfy all six requirements.

1. **Freeze before build.** Make and freeze evals with a timestamp and base SHA before implementation starts.
   Record each edit after freeze with `amend` and give its cause. Report these changes at loop end.

2. **Negative controls.** Each scripted eval has a command that shows the check can give a negative result (E0 pattern).
   Do not trust a green result until a negative control shows the check can find a problem.

3. **End-state surfaces.** Run assertions against the merged tree, a new clone, a deployed artifact, or a local artifact you operate directly.
   Rule 6 uses `artifact-path` for a local artifact at PR scope. Operate the artifact to see its behavior. A working-tree self-report only quotes the diff and does not satisfy this rule.

4. **Oracle independence.** An eval must not share its oracle with the implementation.
   Do not use the same regex, fixture, or test the implementation writes. Derive evals from the task's goal.
   At loop scope, use the outcome the user approved in the native agentic loop's plan or optional `progress.json.scope`.
   A spec or plan can add constraints and surfaces to check. It cannot override that outcome.

5. **Grader independence.** A new subagent grades judgment evals. Give it only `evals.json` and links or paths to the artifact.
   Do not give it the implementation conversation. The neutral assembly script calculates `result`. If you record a change to an eval after a verdict, give it to a new grader.
   The orchestrator must not write `result` by hand or write an eval's `status` to change an existing verdict.

6. **Strongest surface.** If the task names a surface a person sees or uses, test it directly with a P0 eval.
   Examples are a UI, CLI output, a rendered artifact, and a served endpoint. Use the browser, CLI, or HTTP to operate the live artifact. Grep checks on merged code alone do not satisfy this rule.
   At PR scope before merge, use the local artifact (`artifact-path`). At loop scope, use the deployed surface.

   Apply the rule when you write and examine the evals. The gate cannot identify "user-facing" changes.
   For example, greps passed in the run-output noise-strip loop while the live streaming window leaked. A browser eval across the streaming lifecycle found the leak.

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at` or `frozen_sha`, run this check one time for each eval:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

Run this self-check immediately before freezing. If the answer is yes, rewrite the eval. Do not accept it unless all answers are no.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freezing, run each scripted eval's `cmd` and `negative_control` one time. Read their raw output.
The negative control shows that the check can give a negative result. The smoke run shows that the commands can run.
A control can give its correct result if its paired `cmd` does not run at all. You must run this check and the self-check.

Look for these signs of a broken check in the raw output:

- A reporter error without a test summary.
- A module resolution error such as `ERR_MODULE_NOT_FOUND` without an install log.
- An error stack without an assertion result.
- A gate or policy refusal without the command's own output.

In each example the command stopped before it checked the artifact. A non-zero exit alone can look like the required "fail."

Before freeze, rewrite and run a broken `cmd` or `negative_control` again. No `amendments` entry is necessary.
After you set `frozen_at` and `frozen_sha`, record the change with `amend` and give its cause. Keep the assertion unchanged. If the eval has a grader verdict, send it to a new grader as in rule 5.

**Calculate the result.** Do not write the smoke record by hand.
Run `"$SKILL_DIR/../../scripts/post_evals.py" smoke-run <evals.json>` immediately before freezing. It runs each scripted eval's `cmd` and `negative_control`.
It writes the observed exit codes and output excerpts into each eval's `smoke` object and replaces existing contents.
The same script's `validate-structure` command (check 9) refuses a PR-scope scripted eval at level 1 or higher if it has no `smoke`.

A checker that only reads recorded exit codes cannot know that the commands ran. An author who plans to write a script can guess its exit code (`1`, "the assertion fails until I build it").
This occurred in practice. The author had not run the command.

As in rule 5, a neutral script calculates these records. The author must not write them by hand. `smoke-run` records the outputs and exits 0. Check 9 uses the record to accept or refuse the eval.

**Gate-time re-execution (check 10).** Check 9 checks the recorded values and their structure.
A plausible hand-written `smoke` object (`cmd_exit: 1`, control non-zero) can satisfy check 9 without a command run.
At PR scope, check 10 runs each level 1 or higher scripted eval's `cmd` and `negative_control` through `validate-structure`.
Check 10 uses results from the new run. It does not use the values in the record.

If `cmd` or `negative_control` is empty or has only whitespace, the gate refuses before it runs anything.
A whitespace-only command could exit 0 without work because the gate does not check `cmd` polarity.
The gate also refuses an environmental exit (126, 127, timeout, or signal termination) or a control that exits 0.

A `cmd` can exit non-zero at freeze before the build and exit 0 at merge after the build. Check 10 only checks if the two commands can run and if the control exits with the intended non-zero status.
It has the same scope as checks 8 and 9. It applies only to PR scope and excludes level 0 and agent-run evals.

The commands run in the caller's working directory with the same 10s limit as `smoke-run`.
The limit stops the full child group, which usually limits forking commands such as bash scripts and test runners.
A descendant that detaches into its own session, such as a daemon, can run longer and keep the gate open.

Run the gate and `smoke-run` from the repository root so their working directories agree. The script does not check this convention.
A different directory can cause an incorrect refusal. It cannot cause the gate to accept a bad eval.

**Limits of the records.** The local merge check runs each scripted command and control again.
It rejects a command that cannot run or a control that exits 0. It cannot prove the exit code at freeze time.
The GitHub integrity check reads the recorded results as data. It does not run commands from PR comments.

Check 9 refuses three results and accepts a fourth:

- **`cmd` exited 126/127/142/≥128** — command not found, permission denied, timeout, or a signal death.
  The check stopped before it tested the artifact. This finds a `cmd` for a script the author plans to write but has not made.
- **`negative_control` exited 0.** This gives no proof that the check can find a content problem.
  For example, the control file can be in a different tree, or a "removed" tool can stay on `PATH`.
- **`negative_control` exited non-zero because of the environment.** A tool error gives no proof that the control can find a content problem.
  The control must exit non-zero because of its content.
- **Accepted: `cmd` exited non-zero because of the content.** Freeze before build (check 8) occurs before implementation.
  An assertion can then correctly give a negative result. Check 9 accepts this result because a freeze can occur before `cmd` can exit 0.

The check distinguishes "did not run" from "ran and failed". Do not count a skip as a correct negative result.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A frozen scripted check can always give a positive result or always give a negative result. The smoke run only shows that the check runs. It cannot show that the verdict depends on the input.
In loop 8b69e779, an awk formula always exited 1. Correct input with a 39/39 result and incorrect input with an 18/40 result gave the same exit code.
No code change could give that check a positive result.

An eval can add an optional `fixtures` object to the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

If the eval has `fixtures`, `"$SKILL_DIR/../../scripts/post_evals.py" validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula.
The good fixture must give exit 0. The bad fixture must give a non-zero exit. The gate refuses the eval by name if the two fixtures give the same code or if it cannot get a formula from `cmd`.
If derivation does not work, the author must supply `fixtures.formula` explicitly.

Derivation uses the text position of the last top-level pipe. It does not parse shell syntax.
A quoted pipe in an `awk` or `grep` pattern can make the tool cut the quoted string. Supply `fixtures.formula` explicitly.

**Gate scope.** The gate checks only evals with `fixtures`. Without them, the eval follows the same checks as before.
Adding `fixtures` is optional. This gate does not retroactively validate older evals or files. If you do not add `fixtures`, you have no discrimination result.

A positive result only shows that the formula can distinguish the two supplied inputs. It does not prove that the formula tests the correct claim or that the fixtures represent the intended inputs.
It also does not prove that `cmd` and `fixtures.formula` will stay in sync after edits.
This finds the "never fails" defect for the supplied pair. It does not prove the full check correct.

## Verification level rules (self-exemption defence)

Use these conditions to select the level.

- **Verification level 0 (exemption with justification).** Use it only if all these conditions hold:
  - One work unit.
  - No outward or irreversible surface.
  - An existing test or verification criterion checks the task's goal.

  The gate needs a written exemption with a justification. A UI, CLI output, rendered artifact, or served endpoint from rule 6 is an outward surface for the level-0 decision.
  A change to a surface a person uses needs a minimum of level 1 and one P0 eval that operates the artifact.
  This rule only changes the level-0 decision. The level-2 condition below uses its own list of outward changes.

- **Verification level 1 (standard).** Use it if level 0 does not apply and no condition for level 2 applies.
  Write 3–5 end-state evals and a minimum of one negative control. Use P0 and P1.

- **Verification level 2 (full suite).** Use it for three or more work units or an irreversible or outward change.
  The outward changes here are publication, deployment, migration, data removal, and external sends.
  Use the full suite with pre and post surfaces as applicable. Give the GO/NO-GO rule in the artifact.

Give `verification_justification` at each level. For level 0, give the basis for the exemption.
For levels 1 and 2, name the condition that applies (e.g. "2 work-units, no irreversible surface" or "≥3 work-units").

At PR scope, `"$SKILL_DIR/../../scripts/post_evals.py" validate-structure` (check 2) refuses a blank justification.
At loop scope, the orchestrator must refuse a blank justification before the loop ends. The loop hook does not check it.

**The gate calculates a minimum level.** `policy/surface_policy.json` lists the paths for each class:

- Irreversible: `install.py`, `uninstall.py`, `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, and the two `hooks.json` files.
- Outward: `commands/`, `skills/`, `hooks/`, `scripts/`, `agents/`, `packages/codex/`, `policy/`, and `capabilities/`.
- No class: docs and tests.

`scripts/lib/eval_level.py` calculates the minimum from the PR diff and unit count. It gives level 0 only for one work unit with no outward surface.
It gives a minimum of level 1 for an outward surface or two units. It gives level 2 for an irreversible surface or the count in `level_2_work_units` (3).

The `facts{work_units,surfaces}` in `evals.json` give only a lower bound. The tool uses units in `progress.json` if `post_evals.py post --progress` resolves that file.
`post_evals.py post` and each merge path (`merge.py`, Codex `pr_publication_gate`) calculate the minimum from the live diff. They refuse a lower `verification_level` with `level_below_derived`.

At PR scope, the gate also runs `verify_suite`. An oracle edit after `smoke-run` without `amend` gives `suite_hash_mismatch`.
A suite at level 1 or higher without `frozen_hash` gives `not_frozen` or `integrity_stripped`.

If `frozen_sha` is not an ancestor of the branch base, the gate identifies a late freeze. Disclose it. The second line (`coderails-eval-facts v1`) carries `late_freeze=1`.
If the facts line disagrees with the recalculated value, the gate gives `late_freeze_unstamped`.

A diff cannot show the number of work units. Without `--progress` or a declared lower bound, the gate counts one unit. A same-user agent can post a `progress.json` with a lower unit count.
Above the minimum, the level fields guide the selection of an applicable eval set.

The trusted GitHub workflow attests the current SHA's inspection and eval records, provenance fields, policy paths, and bounded diff.
It does not examine the meaning of `verification_level`. Merge authorization depends on that `integrity-review` attestation.

**Freeze provenance.** `smoke-run` sets `integrity_version: 2` on each new level 1 or 2 suite.
Its frozen hash and signature bind `frozen_sha` and `frozen_at`. The retained version 1 suites keep their initial hash and signature.
Git can find a version 1 SHA before the branch base, but cannot prove freeze timing for that suite.

To post a version 1 suite, copy it and keep the initial file. Use `post_evals.py amend` with `frozen_sha <40-hex SHA> frozen_at <ISO8601> timing=unverifiable`.
A late or missing version 2 freeze needs the same signed text with `timing=late` or `timing=unverifiable`. Grade the copy again before you post it.

Posting and local merge checks need a trusted signer and check the branch base.
The GitHub workflow checks the signature bytes and versioned hash. It has no trusted signer list or branch ancestry proof.

## Eval anatomy

Each eval object in the `evals` array carries:

- **ID** — short identifier (e.g. `E1`).
- **`priority`** — `P0` blocks the gate. Correct `P1` before announcement. It does not block the gate.
- **Mode** — `scripted` (deterministic command) or `agent-run` (judgment by a new verifier subagent).
- **Surface** — `merged-state | fresh-clone | artifact-path | deployed`.
  `artifact-path` covers a locally built or locally run artifact: a file path,
  local CLI invocation, or locally served endpoint before merge. Use `deployed` for that endpoint on the live instance after merge.
- **Assertion** — one-line goal-state assertion.
- **Command or verifier instruction** — the scripted command, or the instruction handed to the verifier subagent.
- **Negative control** — a command that shows the check can give a negative result. Scripted mode needs it.
- **`expected`** — what a positive result looks like.

**PR-scope path safety.** Make each `artifact-path` or `merged-state` eval use the ref it tests.
Do not use a shared checkout on the assumption that it contains the PR branch or frozen base SHA. Other work can change that checkout independently of the PR.

For a blob read, use `git show <remote-ref>:<path>`. For a build or run, use a worktree that you keep at that ref. Make the worktree only if missing.

Check the ref first with `git show-ref --verify --quiet` so a missing branch gives an error. Keep the worktree between runs to keep its build cache.
If you make the worktree again each time, the validator can time out before the check finishes.

Check what the eval observes. If the shared checkout's `HEAD` had a different commit from the test ref, would the eval correctly give a negative result?
If the result stays positive, the eval checks the incorrect source.

## GO/NO-GO rule

For GO, all P0 evals must give positive results. A negative P1 result does not block the gate. List unresolved P1 results in the artifact so readers can see the debt.

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
  "result": null,
  "graded_at": null,
  "head_sha": "<SHA the grading ran against>"
}
```

`grading` (`{by, checksum, amendments_at_grade, suite_hash, integrity, chain_len, chain_head}`) gives write-time provenance.
The freeze has no `grading` field. Only `post_evals.py grade-loop` writes it when it grades a loop-scope file (see the Verifier agent contract below).
The field is optional and additive. PR-scope files and existing readers work without it. The `schema_version` stays at 1.

`grade-loop` needs a sibling `progress.json` it can parse with `session_id` and `loop_id`. If a native loop has no such file, write one before grading.
The command stamps `.session_id`, `.loop_id`, and `.revision` from that file. It refuses a missing file, a file it cannot parse, missing IDs, or a file that belongs to a different session or loop.

Scripted PR-scope evals need `smoke` (check 9). The field is additive and does not change `schema_version`.
The `smoke` field is optional at loop scope. The `grade-loop` command runs each scripted `negative_control` (see below).

**Loop-scope controls.** For a loop suite at level 1 or higher, `grade-loop` runs each scripted `negative_control`.
It uses the caller's working directory and a 10s limit. Exit 0 gives `control_passes`. An environmental exit (126/127/>=128) gives `control_env`. The command accepts other non-zero exits.

`grade-loop` also runs each scripted `cmd` again in the same directory with the same limit.
If the recorded status is `pass` but `cmd` exits non-zero, it gives `pass_exit_nonzero`. An environmental exit gives `cmd_env`.
The loop Stop check only tests for the file and its hash with a time limit. It runs no commands.

`grade-loop` also refuses if the identity check does not succeed:

- No `progress.json` gives `progress_missing`.
- An unreadable file or a file without `session_id` or `loop_id` gives `progress_unparseable`.
- A suite with different IDs gives `progress_foreign`.

There is no bypass flag. For an archived suite, put its `progress.json` back. `schema_version` 3 is optional. The command grades schema 2 and records `legacy_progress_schema`.

**Changes to frozen data (Phase F).** `post_evals.py smoke-run` stamps top-level `frozen_hash` with the SHA-256 of the oracle.
It includes each eval's `id, priority, mode, cmd, negative_control, fixtures, expected, assert` and the suite's `task_ref, scope, verification_level`.
It does not include `status, smoke, result, graded_at, grading, amendments, amendment_chain, new_cases` because they can change.

`smoke-run` stamps only a suite with no freeze or grade. If the suite has a freeze, it checks the oracle first and gives `suite_hash_mismatch` for an unrecorded edit.
Record the edit with `amend`, then run the command again.

To edit the oracle after freeze, edit the file. Then run `post_evals.py amend <evals.json> <eval_id> <reason> <actor> [regraded_by]`.
This appends to `amendment_chain[]` (`seq, eval, reason, ts, actor, prev_hash, suite_hash_after, hash`) and to legacy `amendments[]`. The first entry uses `frozen_hash` as `prev_hash`.

`grade-loop` and the reader at loop end can refuse with a printed `reason=<code>`. The codes are `suite_hash_mismatch`, `chain_broken`, `chain_truncated`, and `integrity_stripped`.
`integrity_stripped` means the suite had `frozen_hash` when graded but has no hash after grading. The reader at loop end gives `TAMPERED:<code>`, and the Stop-hook message prints the code.
The row is in `eval_trace.jsonl` next to `evals.json`.

`grading` also records `suite_hash`, `integrity`, `chain_len`, and `chain_head`. These records can show tampering. Signing protects them only from actors without the key.
An actor with the key can rewrite the oracle, chain, and grade stamp together, or truncate and grade again. Transcript forgery is out of scope (`skills/agentic-loop/loop-state.md`).

The hash does not include script files that a `cmd` names. At PR scope, `head_sha` binds those files. At loop scope, the files have no such binding.
A suite without `frozen_hash` can grade as `legacy_unhashed`. The command writes that value to `grading.integrity` and prints and records `reason=legacy_unhashed`.

If an actor removes `frozen_hash` and the `grading` tombstones (`integrity`, `suite_hash`, `chain_*`), the graded suite looks like a legacy suite.
If an actor removes `frozen_hash` before the first grade, `smoke-run` can freeze it again. To show these changes, keep an anchor in a ledger that the same-user key does not control.
Signing has no such anchor. Only the non-authoritative rows in `eval_trace.jsonl` give other records.

**Signing (Phase F, item 4).** `smoke-run` and `amend` write a suite-level `signature` (`{signer, payload, sig}`).
They sign `{frozen_hash, chain_head, chain_len, loop_id, session_id}` with `ssh-keygen -Y sign` in the `coderails-evals` namespace.
The key is in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`. The tool makes it at the first signing with mode 0600. `grade-loop` signs again after it writes the IDs and sets `grading.signed`.

Readers refuse with `signature_invalid`, `signer_unknown`, `signature_missing`, or `key_perms`.
They give `signature_missing` if the signature is gone after `grading.signed` or if `evals.require_signatures: true`. They report an unsigned frozen suite as `legacy_unsigned`.
They report a verifier without `ssh-keygen` or `allowed_signers` as `key_missing`. They report these last two codes without blocking unless signatures are mandatory.

An actor with only the public key can check the signature. An actor without the private key cannot sign changed data. A same-user agent can read the 0600 private key and sign again.
Signing cannot find a rollback to earlier signed data. Only `grading.chain_len` can find some rollbacks. Runbook: `docs/graph-alignment-measurement.md`.

**Gate rules.** `verify_execution` runs through `validate-structure` and `smoke-verify`.
It gives `pass_exit_nonzero` if `status: pass` has a `cmd` that exits non-zero. At freeze, `smoke` can accept a non-zero (TDD-red) `cmd` exit.
If an eval has `fixtures`, its `fixtures.formula` must be the literal tail of `cmd` or the gate gives `fixture_formula_not_in_cmd`. This makes the fixtures test the actual checker text.

This file is the schema's only tracked copy. The package-local `$SKILL_DIR/../../scripts/lib/eval_artifact.py` defines the marker and result format.
`$SKILL_DIR/../../scripts/post_evals.py` checks structure, calculates results, and checks fixture discrimination for `$coderails-codex:post-evals`.
At loop scope, the native agentic-loop orchestrator must read and check the artifact before it reports the loop complete.

## Where evals.json lives

- **Loop scope** — Use the task's scratch directory next to the native agentic loop's optional `progress.json`.
  Keep it out of the repository. Do not commit it.
- **PR scope** — Use the file during work only. The durable artifact is the SHA-bound comment from `$SKILL_DIR/../../scripts/post_evals.py`.
  It has marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> verification_level=<0|1|2> -->`. See the contract below.

## Invocation contract

The package-local `$SKILL_DIR/../../scripts/merge.py` reads the PR-scope artifact from `$coderails-codex:post-evals`.
At loop scope, the native agentic-loop orchestrator reads `evals.json` next to its optional `progress.json`. This contract makes no claim about a custom loop hook.

This skill is invoked at four points:

- **`$coderails-codex:agentic-loop`** — loop scope, before implementation dispatch begins.
- **A planning workflow** — Freeze PR-scope evals before implementation workers start.
  The last task only grades and posts through `$coderails-codex:post-evals`.
- **A debugging workflow** — If a correction will have a PR, freeze PR-scope evals before implementation.
- **Directly by the user.**

Put each unit's eval refs from the plan or loop into its worker prompt. If `progress.json` records the ref but the prompt does not, the worker does not get it.
Give the ref verbatim in the prompt. A pointer to the loop file alone does not satisfy this requirement.

## Verifier agent contract (agent-run evals)

For agent-run evals, start a new Codex subagent with `spawn_agent`. Give it only the `evals.json` content, artifact locations, and the confidence-label contract.
Locations can be a PR number, clone path, artifact path, local endpoint, or deployed surface. Do not give it the implementation conversation, the implementer's summary, or the orchestrator's opinion.

Collect the result with `wait_agent`. Use `send_input` only if the result has missing records. Then use `close_agent`. The verifier gives a status and records that justify it for each eval.
The orchestrator puts only those statuses into `evals.json`.

Only the neutral script calculates and stamps `result`. Use `$SKILL_DIR/../../scripts/post_evals.py` for PR scope or its `grade-loop` command for loop scope.
Do not write `result` by hand. Send amended evals to a new grader. `grade-loop` records the checksum and count of changes in `amendments`.

The stamp can show accidental changes. It cannot show deliberate tampering. The native agentic loop's last audit is the backstop.
