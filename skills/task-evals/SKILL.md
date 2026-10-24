---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
effort: high
---

# Task Evals

Define independent success evals for a non-trivial task before implementation starts. Freeze and grade them.

## Why this skill exists

Coderails has many checks, but the implementer runs many of them.
`superpowers:writing-plans` sets criteria in the same process that later
implements the task. Phase 3 and 3a workers check their own work. Phase 4b
reviews code quality. Phase 13 counts process steps without scoring their
results. The `/merge` gate requires a review artifact bound to the head
SHA. That artifact shows a review step took place. It does not prove that
the task reached its goal.

The public-readiness suite (E0–E10) uses negative controls, checks on
fresh final surfaces, and independent GO/NO-GO grading. This skill applies
that method to other tasks. It separates the person or agent who defines
the checks from the implementer and the grader.

## Prerequisite: gather context before generating evals

Gather context before drafting an eval. Read the project wiki first. It may already state constraints, earlier decisions, and known problems. Read code for details the wiki does not cover. If the project has no wiki (`config.wiki_path` is null), read the codebase.

Send this context read to a sonnet agent. This keeps it separate from the
orchestrator's work, as in `agentic-loop` Phase 2. Ask for concise findings.
Do not ask for raw file dumps. In an agentic loop, use the Phase 2 pre-flight
wiki findings. Do not repeat the read for each skill call.

This is a context-gathering prerequisite, not a verification step — do not conflate it with the gameability self-check or the six anti-gaming rules below.

## The six anti-gaming rules

Every eval must meet all six rules. If an eval fails one rule, it is invalid.

1. **Freeze-before-build.** Generate and freeze evals before implementation.
   Record the time and base SHA. Treat each later edit as an amendment. Give
   it a reason and report it at loop end.
2. **Negative controls.** Give every scripted eval a command that shows its
   check can fail (the E0 pattern). Test the check before trusting a pass.
3. **End-state surfaces.** Check merged state, a fresh clone, a deployed
   artifact, or a locally built artifact that you run directly. For a PR,
   rule 6 names the local `artifact-path` surface. Do not use a working-tree
   self-report as the result. Running the artifact observes its behavior;
   the self-report describes only a diff.
4. **Oracle independence.** Do not reuse the implementation's regex,
   fixture, or test as an eval oracle. Derive the eval from the task goal.
   For a loop, use **`authorising_prompt_raw` in `progress.json`**. This
   post-Phase-0 text is the canonical goal; do not choose between prompt
   versions. `spec.md` restates loop criteria in Phase 2.7a. `plan.md`
   restates them per task. Both can add constraints and concrete surfaces.
   Neither can replace the envelope's goal. The `spec.md` copy comes from
   `progress.json`; it is not another authority.
5. **Grader independence.** Give judgement evals to a fresh subagent. Give
   it only `evals.json` and artifact references. Do not give it the
   implementation conversation. A neutral script computes `result`; the
   orchestrator must not write it. A post-verdict amendment needs a fresh
   grader. The orchestrator must not reverse a verdict by writing a new
   per-eval `status`.
6. **Strongest surface.** If a person sees or uses the goal, at least one
   P0 eval must exercise that surface. Examples are a UI, CLI output,
   rendered artifact, and served endpoint. Use a browser, CLI call, or
   HTTP request to drive the artifact. A grep of merged code is too weak.
   Before merge, run the local `artifact-path` surface. At loop scope, use
   the deployed surface. The eval writer and reviewer must enforce this
   rule; a script cannot tell whether a goal is user-facing. For example,
   a merged-code grep missed noise in a live stream. A browser eval found it.

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

**Compute the smoke result.** Do not write smoke evidence by hand. Run
`scripts/post_evals.py smoke-run <evals.json>` just before freezing. It runs
each scripted eval's `cmd` and `negative_control`. It replaces each `smoke`
object with observed exit codes and output excerpts. For a PR eval at level
1 or higher, `post_evals.py validate-structure` (check 9) rejects a missing
`smoke` object.

An agent can write plausible exit codes without running a command. It could
record `1` for a script that does not yet exist. This caused the earlier
defect. Rule 5 therefore requires a neutral script to record smoke evidence.
`smoke-run` records observations without judging them. It can exit 0 when
the output shows a problem. Check 9 rejects that result.

**Gate-time re-execution (check 10).** Check 9 checks the shape of recorded
evidence. A writer could invent `cmd_exit: 1` and a nonzero control result.
For PR evals at level 1 or higher, check 10 makes `validate-structure`
rerun every `cmd` and `negative_control`. It judges the new observations,
not the recorded numbers.

Check 10 rejects a blank command before running it. It rejects a command
or control that fails because of exit 126, exit 127, timeout, or a signal.
It also rejects a control that exits 0. It does not require `cmd` to pass
before the build. That command can fail at freeze and pass at merge. The
gate checks that both commands run and the control fails for its intended
reason.

Checks 8–10 apply to PR evals. Level 0 and agent-run evals are exempt.
Loop evals keep their existing behavior. Commands run in the caller's
directory with a 10-second limit, as in `smoke-run`. The limit kills the
child process group. A descendant that becomes a daemon can escape the
group and hold the gate open. Run `smoke-run` and the gate from the repo
root so paths agree. The script does not enforce that directory. Running
elsewhere can cause a false refusal.

**Evidence limit.** The local merge check reruns commands and controls.
It cannot prove their freeze-time result because the build can change it.
A writer could enter a false freeze-time exit code that the merge gate
cannot detect. GitHub Actions reads recorded results as data. It never
runs a command from a PR comment.

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

**PR-scope path safety.** An `artifact-path` or `merged-state` eval can read
or build a named ref, such as the PR branch or frozen base SHA. Do not
hardcode the orchestrator's shared checkout and assume it holds that ref.
The shared checkout can move to another commit while the PR stays on its
own ref. For a blob, use `git show <remote-ref>:<path>`. For a build or run,
use a **persistent, create-if-absent** worktree at the exact ref. Check
that the ref exists with `git show-ref --verify --quiet`. A missing branch
must fail, not produce a false pass. Do not remove and recreate that
worktree for each check. That would discard its build cache and can cause
the validator to time out. As a check, imagine the shared checkout's HEAD
is a different commit. The eval must still test the named ref.

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

`grading` records `{by, checksum, amendments_at_grade, suite_hash,
integrity, chain_len, chain_head}`. It is absent at freeze. Only
`post_evals.py grade-loop` writes it when grading a loop file; see the
Verifier agent contract below. It is optional for PR files and existing
readers. It does not raise `schema_version` above 1. At the same write,
`grade-loop` reads the sibling `progress.json` and stamps top-level
`.session_id`, `.loop_id`, and `.revision`. It rejects a missing, invalid,
ID-less, or foreign progress file. A missing file no longer passes.

Check 9 requires `smoke` for scripted PR evals. This adds no schema version.
Loop files can omit `smoke`, as before. `grade-loop` still runs each
scripted loop eval's `negative_control`.

**Loop-scope controls run during grading.** For a loop suite at level 1
or higher, `grade-loop` runs each scripted `negative_control` in the
caller's directory with a 10-second limit. Exit 0 yields
`control_passes`. An environmental exit (126, 127, or at least 128)
yields `control_env`. Another nonzero exit is accepted. It reruns each
scripted `cmd` under the same conditions. A recorded `pass` with a nonzero
command exit yields `pass_exit_nonzero`. An environmental exit yields
`cmd_env`. The loop Stop guard only checks presence and hash within a time
limit; it runs no eval command.

`grade-loop` also checks identity. Missing `progress.json` yields
`progress_missing`. Invalid JSON or missing `session_id`/`loop_id` yields
`progress_unparseable`. A suite stamped with different IDs yields
`progress_foreign`. There is no bypass. Restore `progress.json` to grade
an archived suite. Schema 2 can still grade; it traces
`legacy_progress_schema` instead of requiring schema 3.

**Tamper evidence (Phase F).** `post_evals.py smoke-run` stamps a top-level
`frozen_hash`. It hashes `task_ref`, `scope`, `verification_level`, and each
eval's `id`, `priority`, `mode`, `cmd`, `negative_control`, `fixtures`,
`expected`, and `assert`. It excludes `status`, `smoke`, `result`,
`graded_at`, `grading`, `amendments`, `amendment_chain`, and `new_cases`.
Those fields can change during normal grading.

`smoke-run` stamps a suite only before its first freeze and grade. For a frozen suite, it first checks the oracle. If the oracle changed, it reports `suite_hash_mismatch`. Record the edit with `amend`, then run it again.

To change the oracle after freeze, edit the file and run `post_evals.py amend <evals.json> <eval_id> <reason> <actor> [regraded_by]`. It appends to `amendment_chain[]` and legacy `amendments[]`. Each chain entry has `seq`, `eval`, `reason`, `ts`, `actor`, `prev_hash`, `suite_hash_after`, and `hash`. The first `prev_hash` is `frozen_hash`.

`grade-loop` and the loop completion reader print `reason=<code>` for `suite_hash_mismatch`, `chain_broken`, `chain_truncated`, or `integrity_stripped`. The last code means `frozen_hash` was removed from a suite graded with one. The completion reader returns `TAMPERED:<code>`. The Stop hook prints that code. A trace row is in `eval_trace.jsonl` beside `evals.json`.

`grading` additionally records `suite_hash`, `integrity`, `chain_len`, `chain_head`.

The hash chain detects inconsistent edits. Signing detects edits by an
actor without the key. An actor with the key can rewrite the oracle, chain,
and grading stamp together. The actor can also truncate and regrade. These
changes are not detected. Transcript forgery is outside this check; see
`skills/agentic-loop/loop-state.md`.

Script files a `cmd` references are not hashed (at PR scope they are bound by `head_sha`; at loop scope they are not bound).

A suite with no `frozen_hash` is grandfathered as `legacy_unhashed`: it still grades, `grading.integrity` says so, `reason=legacy_unhashed` is printed and traced, never a silent pass at grade time.

Deleting `frozen_hash` and the `grading` tombstones (`integrity`,
`suite_hash`, `chain_*`) can make a graded suite look like a legacy suite.
Deleting `frozen_hash` before the first grade lets `smoke-run` freeze the
suite again. Detecting either case needs an external ledger beyond the
same-user key. Signing does not provide one. Trace rows are separate
evidence, but they are non-authoritative.

**Signing (Phase F, item 4).** `smoke-run` and `amend` write a suite-level `signature` with `signer`, `payload`, and `sig`. They use `ssh-keygen -Y sign` in the
`coderails-evals` namespace. The key is in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`. It has mode 0600 and is created on first sign. The signed payload holds
`frozen_hash`, `chain_head`, `chain_len`, `loop_id`, and `session_id`. After it stamps the IDs, `grade-loop` signs again and sets `grading.signed`.

Readers reject `signature_invalid`, `signer_unknown`, `signature_missing`, and `key_perms`. A stripped signature after `grading.signed`, or a missing signature
under `evals.require_signatures: true`, yields `signature_missing`. An unsigned frozen suite yields `legacy_unsigned`. A verifier without `ssh-keygen` or
`allowed_signers` yields `key_missing`. The last two conditions are visible but do not block unless signatures are required. A party with only the public key
can verify a signature. A same-user agent can read the 0600 private key and sign a changed suite. Signing also cannot detect a return to an older valid signed
state; `grading.chain_len` partly limits that case. See `docs/graph-alignment-measurement.md` for the runbook.

**Gate rules.** `verify_execution` runs through `validate-structure` and
`smoke-verify`. It rejects `pass_exit_nonzero` when an eval records
`status: pass` but its `cmd` exits nonzero. At freeze time, `smoke` can
record a nonzero `cmd` exit (TDD red). With `fixtures`, `fixtures.formula`
must be the literal tail of `cmd`. Otherwise the gate reports
`fixture_formula_not_in_cmd`.

Use `new_cases[]` when a later independent review finds a case absent from
the frozen suite. No eval covered that case at freeze time. This differs
from `amendments[]`, which changes an existing eval. It also differs from
`withdrawn_proofs`, which records a proof that ran and failed. Fold each
new case into an existing eval and set its `id` to that eval's ID.
`post_evals.py validate-structure` (check 11) rejects an ID absent from
`.evals[]`. It exits nonzero, prints a reason, and writes no stamp. An
absent or empty `new_cases[]` has no effect.

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
