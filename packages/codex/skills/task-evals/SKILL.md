---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
---

# Task Evals

How to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — before implementation starts, not after.

## Why this skill exists

Ordinary implementation checks are often written, run, and graded by the same process.
`$coderails-codex:merge` requires SHA-bound review evidence, but review evidence alone does not prove that the task's goal state was reached.
This skill separates goal-state evals from implementation, requires negative controls, and uses independent grading.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Every
helper command below uses the package-local
`$SKILL_DIR/../../scripts/post_evals.py`.

## Prerequisite: gather context before generating evals

Before drafting an eval, read the project wiki for target context.
It may already state the rules, constraints, decisions, and known problems that the goal must respect.
Read the codebase for anything the wiki does not cover.
If the project has no wiki (`config.wiki_path` is null), read the codebase for all target context.

Dispatch this read to a fresh Codex subagent with `spawn_agent`.
Ask for concise findings. Inside a native agentic loop, reuse an existing pre-flight wiki read.

This is a context-gathering prerequisite, not a verification step — do not conflate it with the gameability self-check or the six anti-gaming rules below.

## The six anti-gaming rules

Every eval must satisfy all six rules. An eval that fails one rule is invalid.

1. **Freeze-before-build.** Generate and freeze evals (timestamp + base SHA) before implementation starts.
   Record later edits as amendments with reasons.
   Report the amendments at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern).
   A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Run assertions against merged state, a fresh clone, or a deployed artifact.
   You can also drive a locally built artifact directly (rule 6's PR-scope `artifact-path`).
   Do not use a working-tree self-report.
   A direct run observes behavior; a self-report only describes the diff.
4. **Oracle independence.** An eval must not share its oracle with the implementation (same regex, same fixture, same test the implementation writes).
   Derive evals from the task's goal state, not its implementation steps.
   At loop scope, use the exact authorising outcome recorded in the native agentic loop's plan or optional `progress.json.scope`.
   A spec or plan may add constraints and assertable surfaces, but it never overrides that outcome.
5. **Grader independence.** A fresh subagent grades judgement evals.
   Give it only `evals.json` and artifact references.
   The orchestrator never hand-writes the `result` field; a neutral assembly script computes it.
   An eval amended after a grader verdict returns to a fresh grader for re-grading; the orchestrator never writes a per-eval `status` that flips an existing verdict.
6. **Strongest surface.** If the goal names something a person uses or sees, at least one P0 eval must use that surface.
   Examples include a UI, CLI output, a rendered artifact, and a served endpoint.
   Drive the running artifact through a browser, CLI call, or HTTP request.
   A grep of merged code alone is not enough.
   Before a PR merges, use the locally run artifact (`artifact-path`).
   At loop scope, use the deployed surface.
   No script can decide whether a feature is user-facing, so the author and reviewer must check this rule.
   For example, merged-code greps missed noise in a live streaming window.
   An in-browser eval across the stream found it.

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at`/`frozen_sha` on any eval, run this check against it once:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

Run this self-check once per eval, immediately before freezing. Rewrite an eval that fails it.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freezing, run every scripted eval's `cmd` and `negative_control` once.
Read the raw output. The negative control proves that a check *can fail*.
The smoke-run proves that the check *can execute at all*. A negative control can work even when its paired `cmd` never runs.
The self-check and smoke-run are separate requirements; do both.

A broken check can show a reporter-loading error in place of a test summary.
It can show a module-resolution error (e.g. `ERR_MODULE_NOT_FOUND`) in place of an install log.
It can show a stack trace or a gate denial in place of the command's own result.
In each case, the command did not reach the artifact it claims to check.
A non-zero exit alone could falsely appear to be a valid failure.

If you find a broken `cmd` or `negative_control` before freezing, rewrite it and run it again.
No amendment is needed. If you find it after stamping `frozen_at`/`frozen_sha`, use the amendment path: record the reason and leave the assertion unchanged.
If that eval already has a grader verdict, get a fresh grade under rule 5.

**The result is computed, not attested.** Do not hand-write the smoke evidence.
Run `"$SKILL_DIR/../../scripts/post_evals.py" smoke-run <evals.json>` immediately before freezing.
It runs each scripted eval's `cmd` and `negative_control`.
It writes the observed exit codes and output excerpts to each eval's `smoke` object. It replaces any earlier `smoke` value.
The same script's `validate-structure` command (check 9) then refuses any pr-scope verification_level≥1 scripted eval lacking one.

The split matters. A checker that only *reads* recorded exit codes trusts numbers the agent wrote.
An agent could write the expected code for a script that does not exist yet: `1`, meaning "the assertion fails until I build it".
That was the real defect.
Rule 5 applies to smoke evidence: a neutral script computes it, and the author never hand-writes it.
`smoke-run` records without judging.
It returns 0 even when the observation is bad, because check 9 must decide whether to refuse.

**Gate-time re-execution (check 10).** Check 9 validates the *shape* of recorded evidence, including numbers written by the author.
A hand-written `smoke` object could claim `cmd_exit: 1` and a non-zero control for commands that never ran.
Check 10 closes that gap.
At PR scope, `validate-structure` executes every `cmd` and `negative_control` for scripted evals with `verification_level` ≥1.
It judges the observed results, not the recorded numbers.

The gate refuses an empty or whitespace-only `cmd` or `negative_control` before execution.
A blank command has nothing to test. A whitespace-only `cmd` could otherwise exit 0 as a no-op and escape the ungated command-polarity check.
The gate also refuses a leg that fails for an environmental reason (126/127/timeout/signal death), or a control observed to exit 0.
It deliberately does NOT judge `cmd` polarity.
Freeze-before-build allows a command to fail at freeze and pass at merge.
The gate recomputes only build-independent facts: both legs resolve, and the control fails as defined.

This has the same scope as checks 8 and 9: PR scope only.
Verification level 0 and agent-run evals are exempt; loop scope is unchanged.
Commands run in the caller's cwd with the same 10s cap as `smoke-run`.
The cap kills the child's process group, so normal child processes are bounded too.
A daemonizing descendant can escape that group and hold the gate open longer.
The documented flow runs both checks from the repo root to keep their paths aligned.
The script does not enforce that convention. A run from another cwd can only fail closed with a false refusal, not a false pass.

**Evidence limit.** The local merge check runs each scripted command and control again.
It rejects a command that cannot run or a control that passes.
It cannot prove what the command returned when the eval was frozen.
The GitHub Actions integrity check reads the recorded results as data. It never runs a command from a PR comment.

Check 9 refuses three outcomes, and deliberately permits a fourth:

- **`cmd` exited 126/127/142/≥128** — command not found, permission denied, timeout, or a signal death.
  The check never reached the artifact it claims to test.
  This is what catches a `cmd` naming a script that was only ever intended to exist.
- **`negative_control` exited 0** — a control that passes proves nothing. This is what catches a control whose file sat outside the tree being validated, or one that "removed" a tool still present on `PATH`.
- **`negative_control` exited non-zero for an environmental reason** — non-zero alone is not enough, because a control that errors out on its own tooling is just as vacuous as one that passes.
  The control must fail for a *content* reason.
- **Permitted: `cmd` exited non-zero for a content reason.** Freeze-before-build (check 8) means the feature is not built at freeze, so a failing `cmd` is the expected case.
  Check 9 keys on the *shape* of the outcome, never its polarity — requiring `cmd` to pass would contradict check 8 and block every honest freeze.

Separate "did not run" from "ran and failed". A skipped check cannot count as a valid failure.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A frozen scripted check can fail in two ways: it may never pass, or it may never fail.
The smoke-run only proves that the check executes. It does not prove that the result changes with the input.
In loop 8b69e779, an awk formula always exited 1.
It gave the same result for a genuine 39/39 pass and a genuine 18/40 fail.

An eval may carry an optional `fixtures` object on top of the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

When `fixtures` is present, run `"$SKILL_DIR/../../scripts/post_evals.py" validate-discriminating`.
It pipes `fixtures.good` and `fixtures.bad` into the formula. The good input must exit 0; the bad input must exit non-zero.
The command names and rejects an eval when both inputs give the same exit code.
It also rejects an eval when it cannot derive the formula from `cmd`.
In that case, supply `fixtures.formula` explicitly.
The derivation splits at the last top-level pipe by text position; it does not parse shell syntax.
A quoted pipe inside an `awk` or `grep` pattern therefore also requires `fixtures.formula`.

**Honest boundary, stated plainly:** this gate validates only checks that carry `fixtures`.
Checks without `fixtures` are grandfathered — validated exactly as they were before this gate existed, with zero behaviour change.
Adding `fixtures` is optional and does not validate an older eval retroactively.
An eval without `fixtures` has no discrimination proof from this gate.
A pass with `fixtures` proves only that the formula distinguishes those two inputs.
It does not prove that the formula tests the right claim.
It does not prove that `cmd` and `fixtures.formula` stay aligned after edits.
It does not prove that the fixtures represent other inputs.
This gate closes the "never fails" class of defect; it is not a general correctness proof of the check.

## Verification level rules (self-exemption defence)

Use concrete predicates, not vibes.

- **Verification level 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state.
  The exemption is still a written artifact — the gates accept a justified exemption, never an absence.
  A UI, CLI output, rendered artifact, or served endpoint is an outward surface for this predicate.
  A change to one of these surfaces needs at least `verification_level` 1.
  It also needs at least one P0 eval that drives the artifact, as rule 6 requires.
  This rule only limits level 0.
  A user-facing change alone does not require level 2.
  Level 2 still applies to publish, deploy, migration, data deletion, or external send.
- **Verification level 1 (standard):** anything above verification_level 0 that doesn't meet a verification_level-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Verification level 2 (full suite):** ≥3 work-units OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send).
  Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

Every `verification_level` needs a `verification_justification`.
At level 0, state why the exemption applies.
At level 1 or 2, name the predicate that applies.
Examples are "2 work-units, no irreversible surface" and "≥3 work-units".
A blank justification is refused by `"$SKILL_DIR/../../scripts/post_evals.py" validate-structure` (check 2) at PR scope.
At loop scope, the native agentic-loop orchestrator must reject a blank justification before completion; no loop hook supplies that check.

Verification level fields remain planning metadata for selecting an appropriate eval set.
The trusted GitHub Actions workflow does not judge verification_level semantics.
It checks the current SHA's review/eval evidence, provenance fields, policy paths, and bounded diff as data.
Merge authorization depends on its `integrity-review` status after the server rule is active.

## Eval anatomy

Each eval object in the `evals` array carries:

- **ID** — short identifier (e.g. `E1`).
- **Priority** — `P0` blocks the gate; `P1` must be fixed before announcing but doesn't block.
- **Mode** — `scripted` (deterministic command) or `agent-run` (judgement, graded by a fresh verifier subagent).
- **Surface** — `merged-state | fresh-clone | artifact-path | deployed`.
  `artifact-path` covers a local file, CLI invocation, or served endpoint before merge.
  Use `deployed` for that endpoint on the live instance after merge.
- **Assertion** — one-line goal-state assertion.
- **Command or verifier instruction** — the scripted command, or the instruction handed to the verifier subagent.
- **Negative control** — required for scripted mode: a command proving the check can fail.
- **Expected outcome** — what a pass looks like.

**PR-scope path safety.** Bind each `artifact-path` or `merged-state` eval to the ref it tests.
Do not assume that a shared checkout contains the PR branch or frozen base SHA.
Other work can change that checkout independently of the PR.
For a blob read, use `git show <remote-ref>:<path>`.
For a build or run, use a persistent worktree of the exact ref.
Create the worktree only if absent.
Check the ref first with `git show-ref --verify --quiet` so a missing branch fails.
Keep the worktree between runs to retain its build cache.
Recreating it for each run can push a warm check past the validator's timeout.
Sanity-check: if the shared checkout's `HEAD` were on a totally different commit than the ref under test, would this eval still (correctly) fail?
If not, it's observing the wrong thing.

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
  "result": null,
  "graded_at": null,
  "head_sha": "<SHA the grading ran against>"
}
```

`grading` records `{by, checksum, amendments_at_grade, suite_hash, integrity, chain_len, chain_head}`.
It is absent at freeze.
`post_evals.py grade-loop` writes it when it grades a loop-scope file.
PR-scope files and existing readers accept its absence.
Adding it does not bump `schema_version` past 1.
`grade-loop` requires a parseable sibling `progress.json` with `session_id` and `loop_id`.
A native loop without that file must write it before grading.
The command stamps `.session_id`, `.loop_id`, and `.revision` from the file.
It refuses a missing, invalid, id-less, or foreign file.

`smoke` is required on scripted evals at PR scope (check 9) and carries no `schema_version` bump: it is additive, and loop-scope files tolerate its absence.
Loop scope does not require `smoke`, but `grade-loop` executes each scripted `negative_control` (see below).

**Loop-scope controls run during grading.** `grade-loop` runs each scripted `negative_control` in a level 1 or 2 loop suite.
It uses the caller's working directory and a 10-second limit.
Exit 0 gives `control_passes`.
An environmental exit (126, 127, or at least 128) gives `control_env`.
Other non-zero exits are accepted.
`grade-loop` also runs each scripted `cmd` with the same directory and limit.
If a recorded pass exits non-zero, it gives `pass_exit_nonzero`.
An environmental exit gives `cmd_env`.
The loop-stop guard stays a time-bounded presence-and-hash check; it executes nothing.
`grade-loop` checks identity before grading.
A missing `progress.json` gives `progress_missing`.
An invalid file or missing session or loop ID gives `progress_unparseable`.
A suite stamped with different IDs gives `progress_foreign`.
There is no bypass flag; restore `progress.json` for an archived suite.
`schema_version` 3 is not required (schema 2 grades, traced `legacy_progress_schema`).

**Tamper-evidence (Phase F).** `post_evals.py smoke-run` stamps a top-level `frozen_hash`.
It is the SHA-256 hash of the oracle.
The oracle includes each eval's `id, priority, mode, cmd, negative_control, fixtures, expected, assert` and the suite's `task_ref, scope, verification_level`.
`status, smoke, result, graded_at, grading, amendments, amendment_chain, new_cases` are excluded because they change legitimately.

`smoke-run` stamps only a suite that has never been frozen or graded.
On a frozen suite, it first checks the oracle.
If the suite changed, it refuses `suite_hash_mismatch`.
Record the change with `amend`, then run it again.

To change an oracle after freeze, edit the file and run `post_evals.py amend <evals.json> <eval_id> <reason> <actor> [regraded_by]`.
It appends to `amendment_chain[]` and the legacy `amendments[]`.
Each chain entry records `seq, eval, reason, ts, actor, prev_hash, suite_hash_after, hash`.
The first `prev_hash` equals `frozen_hash`.

`grade-loop` and the loop completion reader print `reason=<code>` when they refuse a suite.
Codes include `suite_hash_mismatch`, `chain_broken`, `chain_truncated`, and `integrity_stripped`.
The last code means `frozen_hash` was deleted from a suite graded with one.
The completion reader returns `TAMPERED:<code>` and the Stop-hook message prints that code; the trace row is in `eval_trace.jsonl` beside `evals.json`.

`grading` additionally records `suite_hash`, `integrity`, `chain_len`, `chain_head`.

Honest trust boundary: this is tamper-EVIDENT, not adversary-proof.
Signing detects these edits only when the actor lacks the key.
An actor with the key can rewrite the oracle, chain, and grading stamp together.
The same actor can truncate and regrade.
Transcript forgery is outside this check (`skills/agentic-loop/loop-state.md`).

Script files a `cmd` references are not hashed (at PR scope they are bound by `head_sha`; at loop scope they are not bound).

A suite with no `frozen_hash` is treated as `legacy_unhashed`. It can still receive a grade.
`grading.integrity` records this state, and grading prints and traces `reason=legacy_unhashed`.

Deleting `frozen_hash` and the `grading` fields (`integrity`, `suite_hash`, `chain_*`) makes a graded suite look like a legacy suite.
Deleting `frozen_hash` before the first grade lets `smoke-run` freeze it again.
Both cases need an external ledger outside the same-user key.
Signing does not provide that ledger.
Trace rows offer other evidence, but they are not authoritative.

**Signing (Phase F, item 4).** `smoke-run` and `amend` write a suite-level `signature` with `signer`, `payload`, and `sig`.
They use `ssh-keygen -Y sign` in the `coderails-evals` namespace.
The key is in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys` with mode 0600; the first sign creates it.
The signature covers `{frozen_hash, chain_head, chain_len, loop_id, session_id}`.
`grade-loop` signs again after it stamps the IDs and sets `grading.signed`.
Readers can report `signature_invalid`, `signer_unknown`, `signature_missing`, or `key_perms`.
`signature_missing` applies when a signed grade loses its signature or `evals.require_signatures: true` is set.
An unsigned frozen suite reports `legacy_unsigned`. A verifier without `ssh-keygen` or `allowed_signers` reports `key_missing`.
The last two reports are loud but do not block unless signatures are required.
The signature lets a holder of the public key detect edits made without the private key.
A same-user agent can read the 0600 key and sign again.
It also cannot detect rollback to an older valid signature; `grading.chain_len` gives partial protection.
Runbook: `docs/graph-alignment-measurement.md`.

**Gate rules.** At `verify_execution`, a recorded pass with a non-zero `cmd` exit gives `pass_exit_nonzero`.
Both `validate-structure` and `smoke-verify` use this check.
A freeze-time `smoke` still accepts a non-zero `cmd` exit before the feature exists.
When `fixtures` are present, `fixtures.formula` must be the literal tail of `cmd` (`fixture_formula_not_in_cmd`), so fixtures run against the real checker text.

This file is the schema's only tracked copy.
The package-local `$SKILL_DIR/../../scripts/lib/eval_artifact.py` defines the marker and result format.
`$SKILL_DIR/../../scripts/post_evals.py` validates structure, computes results, and checks fixture discrimination for `$coderails-codex:post-evals`.
At loop scope, the native agentic-loop orchestrator must read and verify the artifact before reporting completion.

## Where evals.json lives

- **Loop scope** → the task-specific scratch directory beside the native agentic loop's optional `progress.json`, outside the repo and never committed.
- **PR scope** → the file is working material only. The durable artifact is the SHA-bound PR comment posted by `$SKILL_DIR/../../scripts/post_evals.py` (marker `<!-- coderails-eval-summary v1 pr=<N> head_sha=<SHA> result=<GO|NO-GO> verification_level=<0|1|2> -->`) — see the invocation contract below.

## Invocation contract

The package-local `$SKILL_DIR/../../scripts/merge.py` reads the PR-scope artifact posted by `$coderails-codex:post-evals`.
For loop scope, the native agentic-loop orchestrator reads the `evals.json` beside its optional `progress.json`; no custom loop hook is claimed.

This skill is invoked at four points:

- **`$coderails-codex:agentic-loop`** — loop scope, before implementation dispatch begins.
- **A planning workflow** — PR scope, frozen before implementation dispatch begins; its final task only grades and posts via `$coderails-codex:post-evals`.
- **A debugging workflow** — PR scope, frozen before the fix is implemented when the fix will carry a PR.
- **Directly by the user.**

A plan's or loop's per-work-unit eval refs must travel in worker prompts.
A ref recorded only in `progress.json` and absent from the worker's prompt does not exist for that worker.
Every worker prompt that owns a unit with an eval ref must carry that ref verbatim, not just a pointer to the loop state file.

## Verifier agent contract (agent-run evals)

For agent-run evals, spawn a fresh Codex subagent with `spawn_agent`.
Its prompt contains `evals.json`, artifact references, and the confidence-label contract.
Artifact references can include the PR number, clone path, artifact path, local endpoint, or deployed surface.
Do not include other context.
It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion.
Collect the result with `wait_agent`. If evidence is missing, use
`send_message` while the verifier runs or `followup_task` after it ends.
The verifier returns per-eval status plus evidence; the orchestrator folds those statuses into `evals.json` — nothing more.
Compute and stamp `result` in a separate neutral step.
Use `$SKILL_DIR/../../scripts/post_evals.py` for PR scope.
Use that script's `grade-loop` command for loop scope.
The orchestrator never writes `result`.
An amended eval goes to a fresh grader, and `grade-loop` records checksum and amendment-count provenance.
The stamp detects accidental drift, not deliberate tampering; the native agentic-loop's final audit remains the backstop.
