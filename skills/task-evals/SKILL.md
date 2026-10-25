---
name: task-evals
description: Freeze independent, game-resistant task evals before implementation. Use at task intake, in an agentic loop, when writing a plan, or on direct request. Grade them for PR merge or loop completion.
effort: high
---

# Task Evals

How to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — before implementation starts, not after.

## Why this skill exists

Implementation checks often come from the same process that builds and
grades the work. A SHA-bound review artifact proves that review occurred;
it does not prove the task goal was met. This skill freezes goal-state evals
before implementation. It requires negative controls, direct end-state
checks, and independent grading.

## Prerequisite: gather context before generating evals

Before drafting an eval, read the project wiki for goal constraints, prior
decisions, and known problems. Read source for anything the wiki does not
cover. If `config.wiki_path` is null, use source for all target context.

Dispatch the context read to a sonnet agent. Ask for concise findings,
not raw file dumps. Inside an agentic loop, reuse the Phase 2 pre-flight
wiki findings when they cover this task.

This is a context-gathering prerequisite, not a verification step — do not conflate it with the gameability self-check or the six anti-gaming rules below.

## The six anti-gaming rules

Every eval this skill generates must satisfy all six. These are generation requirements, not descriptions of an ideal — an eval that fails one of them is not a valid eval.

1. **Freeze-before-build.** Evals are generated and frozen (timestamp + base SHA) before implementation starts. Post-freeze edits are amendments with recorded reasons — visible, auditable, reported at loop end.
2. **Negative controls.** Every scripted eval carries a command demonstrating the check *can* fail (E0 pattern). A check that has never failed proves nothing; the tooling itself must be validated before its green is trusted.
3. **End-state surfaces.** Assertions run against merged state, fresh clone, deployed artifact, or a locally built artifact driven directly (rule 6's pr-scope `artifact-path`) — never working-tree self-reports: driving a locally run artifact observes end-state behaviour; a self-report just quotes the diff.
4. **Oracle independence.** Do not reuse the implementation's regex,
   fixture, or newly written test as an eval oracle. Derive evals from the
   task goal, not implementation steps. At loop scope, use the exact
   post-Phase-0 `authorising_prompt_raw` string in `progress.json` as the
   goal source. `spec.md` and `plan.md` can add constraints and concrete
   surfaces; their restated criteria do not override that string.
5. **Grader independence.** Judgement evals are graded by a fresh subagent that receives only `evals.json` + artifact references — never the implementation conversation. The orchestrator never hand-writes the `result` field; a neutral assembly script computes it. An eval amended after a grader verdict returns to a fresh grader for re-grading; the orchestrator never writes a per-eval `status` that flips an existing verdict.
6. **Strongest surface.** If a person uses or sees the result, at least
   one P0 eval must exercise that surface. Examples include a UI, CLI
   output, rendered artifact, or served endpoint. Drive it with a browser,
   CLI call, or HTTP request. A code grep alone cannot show what a user
   sees. Before PR merge, use a locally run artifact (`artifact-path`).
   At loop scope, use the deployed surface. No script can decide whether
   a task is user-facing, so the author and reviewer check this rule.

## Gameability self-check (mandatory before freezing)

Before stamping `frozen_at`/`frozen_sha` on any eval, run this check against it once:

*"Can the implementer pass this eval by (a) editing the eval, (b) asserting on the working tree, (c) self-reporting, or (d) reusing its own oracle? Any yes → rewrite."*

This runs once per eval, immediately before freezing. An eval that fails the self-check is rewritten, not annotated or excused — there is no partial pass on this check.

## Freeze-time smoke-run (mandatory, separate from the gameability self-check)

Immediately before freezing, run each scripted `cmd` and its
`negative_control`. Read their raw output. The negative control proves
that a check can fail. The smoke-run proves that each command can run.
A control can work when its paired `cmd` does not. Keep the gameability
self-check and smoke-run as separate required steps.

A broken check can show a reporter-load or module-resolution error instead
of a test result. A stack trace or gate denial can also show that it never
reached the target artifact. Do not count that nonzero exit as a valid
content failure.

What to do on discovery depends on timing: at freeze time the file is not yet frozen, so a broken `cmd` or `negative_control` is simply rewritten and re-run — no amendment needed, nothing to record. Discovered after `frozen_at`/`frozen_sha` are stamped, it goes through the amendment path instead: recorded reason, assertion left unchanged, and if a grader verdict already exists for that eval, a fresh re-grade per rule 5.

**The result is computed, not attested.** Do not hand-write the smoke evidence. Run `scripts/post_evals.py smoke-run <evals.json>` immediately before freezing: it executes every scripted eval's `cmd` and `negative_control`, and writes the observed exit codes and output excerpts into a `smoke` object on each eval, overwriting whatever was there. `post_evals.py validate-structure` (check 9) then refuses any pr-scope verification_level≥1 scripted eval lacking one.

The split matters. A checker that only reads recorded exit codes can accept
made-up numbers. `smoke-run` computes those numbers by running the commands;
the author must not write them. It records observations without judging them.
It can return 0 even when an observed outcome is invalid. Check 9 makes the
refusal.

**Gate-time re-execution (check 10).** Check 9 reads recorded smoke evidence.
A plausible handwritten `smoke` object could pass that check alone. At PR
scope, `validate-structure` also runs each verification-level-1-or-higher
scripted `cmd` and `negative_control`. It uses observed results, not the
recorded exit codes. It refuses a blank command, an environmental failure
(exit 126, 127, timeout, or signal death), or a control that exits 0. If
an eval is recorded as `pass`, it also refuses a `cmd` that exits nonzero.
At freeze time, a `cmd` may fail for a content reason because the work has
not been built yet. Agent-run and level-0 evals are exempt from this PR
check; loop scope uses its own grade path.

Each command runs in the caller's cwd with a ten-second cap. A timeout
kills the child's process group. A descendant that starts its own session
can escape that group. Run `smoke-run` and validation from the repo root
so relative paths resolve in the same way; the script does not enforce
that cwd convention.

**Evidence limit.** The local merge check runs each scripted command and control again. It rejects a command that cannot run or a control that passes. It cannot prove what the command returned when the eval was frozen. The GitHub Actions integrity check reads the recorded results as data. It never runs a command from a PR comment.

Check 9 refuses three outcomes, and deliberately permits a fourth:

- **`cmd` exited 126/127/142/≥128** — command not found, permission denied, timeout, or a signal death. The check never reached the artifact it claims to test. This is what catches a `cmd` naming a script that was only ever intended to exist.
- **`negative_control` exited 0** — a control that passes proves nothing. This is what catches a control whose file sat outside the tree being validated, or one that "removed" a tool still present on `PATH`.
- **`negative_control` exited non-zero for an environmental reason** — non-zero alone is not enough, because a control that errors out on its own tooling is just as vacuous as one that passes. The control must fail for a *content* reason.
- **Permitted: `cmd` exited non-zero for a content reason.** Freeze-before-build (check 8) means the feature is not built at freeze, so a failing `cmd` is the expected case. Check 9 keys on the *shape* of the outcome, never its polarity — requiring `cmd` to pass would contradict check 8 and block every honest freeze.

This is the pass/skip/fail distinction applied where it is load-bearing: "did not run" is separated from "ran and failed", so a skip can no longer read as compliance.

## Discriminating-check gate (mechanical, optional, `fixtures`-only)

A scripted check can be unable to pass or unable to fail. The smoke-run
proves only that it executes. It does not prove that its result changes
with input. In loop 8b69e779, an awk formula always exited 1. It gave
the same result for a genuine 39/39 pass and an 18/40 fail.

An eval may carry an optional `fixtures` object on top of the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

When `fixtures` is present, `scripts/post_evals.py validate-discriminating`
pipes `fixtures.good` and `fixtures.bad` into the formula. Good input
must exit 0; bad input must exit nonzero. The command rejects an eval
when both give the same exit code. It also rejects an eval when it cannot
derive the formula from `cmd`. Supply `fixtures.formula` in that case.
The derivation splits at the last top-level pipe by text position, not
by shell syntax. A quoted pipe in an awk or grep pattern therefore needs
an explicit formula.

This gate checks only evals with `fixtures`. Existing evals without them
keep their earlier validation. Adding fixtures is optional and does not
retroactively test old evals. A pass proves that the formula distinguishes
these two inputs. It does not prove that the formula tests the right
claim, stays aligned with `cmd`, or covers other inputs.

## Verification level rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Verification level 0 (exempt, justified):** one work unit, no outward
  or irreversible surface, and an existing test or criterion that covers
  the goal. The exemption still needs a written artifact. A UI, CLI
  output, rendered artifact, or served endpoint is an outward surface for
  this rule. It needs at least level 1 and a P0 eval that drives the
  artifact. A user-facing change alone does not require level 2.
- **Verification level 1 (standard):** anything above verification_level 0 that doesn't meet a verification_level-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Verification level 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

Every level needs `verification_justification`. At level 0, explain the
exemption. At levels 1 and 2, name the predicate, such as two work units
without an irreversible surface or at least three work units. At PR
scope, `post_evals.py validate-structure` check 2 refuses a blank value.
At loop scope, `loop_dispatch_guard.py` checks it at dispatch and
`loop_state_guard.py` and `loop_stall_guard.py` check it at completion
through `loop_evals.read_loop_evals`. The PR merge reader sees only the
posted marker, which omits justification. PR enforcement therefore occurs
when the writer posts the eval artifact.

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

**PR-scope path safety.** Bind an `artifact-path` or `merged-state` eval
to the ref it tests. Do not assume a shared checkout contains the PR
branch or frozen base SHA; other work can change it. For a blob read,
use `git show <remote-ref>:<path>`. For a build or run, use a persistent
worktree of the exact ref. Create it only when absent. Check the ref
with `git show-ref --verify --quiet` so a missing branch fails loudly.
Keep the worktree between runs to retain its build cache. Recreating it
for every run can make a check exceed the validator timeout. Check that
the eval would still observe the intended ref if the shared checkout's
HEAD moved elsewhere.

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

`grading` records `by`, `checksum`, `amendments_at_grade`, `suite_hash`,
`integrity`, `chain_len`, and `chain_head`. It is absent at freeze.
`post_evals.py grade-loop` writes it for loop scope. PR-scope files and
existing readers accept its absence. This additive field keeps
`schema_version` at 1.

At the same write, `grade-loop` reads the sibling `progress.json` and
stamps `session_id`, `loop_id`, and `revision`. It refuses a missing,
invalid, id-less, or foreign state file.

`smoke` is required on scripted evals at pr scope (check 9) and carries no `schema_version` bump: it is additive, and loop-scope files — which check 9 does not gate — tolerate its absence exactly as before. Loop scope does not require `smoke`, but `grade-loop` executes each scripted `negative_control` (see below).

**Loop-scope controls run during grading.** For a level-1-or-higher loop
suite, `grade-loop` runs each scripted `negative_control` and `cmd` from
the caller's cwd with a ten-second cap.

- A control exit of 0 gives `control_passes`.
- A control environmental exit (126, 127, or at least 128) gives
  `control_env`.
- Another nonzero control exit is accepted.
- A recorded pass whose `cmd` exits nonzero gives `pass_exit_nonzero`.
- An environmental `cmd` exit gives `cmd_env`.

The loop-stop guard checks presence and hashes; it runs no eval command.
`grade-loop` refuses a missing `progress.json` as `progress_missing`, an
invalid or id-less one as `progress_unparseable`, and a suite stamped with
other IDs as `progress_foreign`. There is no bypass flag. Restore the
state file for an archived suite. Schema 2 can still grade and emits
`legacy_progress_schema`; schema 3 is not required by this grade.

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

**Gate rules added.** At the gate (`verify_execution`, via `validate-structure` and `smoke-verify`) an eval recorded `status: pass` whose `cmd` exits non-zero is refused `pass_exit_nonzero`; freeze-time `smoke` still accepts a non-zero (TDD-red) `cmd` exit. When `fixtures` are present, `fixtures.formula` must be the literal tail of `cmd` (`fixture_formula_not_in_cmd`), so fixtures run against the real checker text.

`new_cases[]` records a case that independent review found missing from
the frozen suite. It differs from `amendments[]`, which changes an
existing eval, and from `withdrawn_proofs`, which records an observed
failed proof. Fold each new case into a real eval and set its `id` to
that eval's `.evals[].id`. `post_evals.py validate-structure` check 11
refuses an unmatched ID. An absent or empty array changes nothing.

The Claude and Codex skill files both describe this eval format. The
enforcement code is in `scripts/lib/eval_artifact.py`, `scripts/post_evals.py`,
and the `loop_state_guard` loop-scope gate. `post_evals.py` validates
structure, computes results, and checks discriminating fixtures. The loop
guard blocks completion when a loop with at least one work unit lacks a
passing loop-scope `evals.json`.

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

For an agent-run eval, send a fresh sonnet subagent only:

1. The `evals.json` content.
2. Artifact references, such as the PR number, clone path, local artifact
   or endpoint, or deployed surface.
3. The confidence-label contract.

Do not send the implementation conversation, implementer's summary, or
orchestrator's opinion. The grader returns a status and evidence for each
eval. Fold only that fresh output into `evals.json`.

Compute `result` in a separate neutral step. Use `post_evals.py` for PR
scope and `post_evals.py grade-loop` for loop scope. The orchestrator
never writes `result`.

If an eval changes after a grader verdict, send it to a new grader.
Record that grader in `regraded_by`. `grade-loop` refuses a post-verdict
amendment with no `regraded_by` value.

At loop scope, `grade-loop` writes a `grading` object with `by`, a checksum
over eval statuses and result, and `amendments_at_grade`. The loop-stop
guard checks this stamp before it accepts GO or VERIFICATION_LEVEL0. The
stamp catches accidental status drift and an increased amendment count.
It does not prove that the author could not alter the file deliberately.

The amendment-count check cannot detect a status flip with no amendment,
an amendment edited in place, or a flip folded in before the first grade.
`amendments_at_grade` is outside the checksum and can itself be edited.
Use the Phase 13 audit as an additional check on those limits.

Amend the graded file in place. If the file is regenerated, it loses the
stamp. `grade-loop` still treats any remaining `graded_at` or `result`
as a prior verdict and refuses to grade it as new.
