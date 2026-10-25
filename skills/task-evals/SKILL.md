---
name: task-evals
description: 'Use at task intake, before implementation starts, to turn any non-trivial task into a frozen, graded set of independent, game-resistant success evals — inside an agentic loop or not. Trigger at loop scope (per-loop and per-work-unit), when a plan is written, or directly on user request. Produces a frozen evals.json (schema_version 1) defining game-resistant success evals for a task, designed to gate merge at pr scope and loop completion at loop scope. Not self-verification — evals must not share an oracle with the implementation.'
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

Immediately before freezing, execute every scripted eval's `cmd` and its `negative_control` once, for real, and read the raw output. This is a different question from rule 2 and from the self-check above: the negative control proves a check *can fail*; the smoke-run proves the check *can execute at all*. A negative control can pass cleanly while the `cmd` it pairs with never runs — so passing the self-check does not satisfy this step, and this step does not substitute for the self-check either. Both are required.

A broken instrument looks like this in the raw output: a reporter-loading error instead of a test summary, a module-resolution error (e.g. `ERR_MODULE_NOT_FOUND`) instead of an install log, a stack trace where an assertion result should be, or a gate/policy denial instead of the command's own output. In every case the tell is the same — the output shows the command never reached the artifact it claims to check, even though the process exited non-zero and would otherwise read as a passing "fail."

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

A frozen, blind-authored scripted check can be broken in itself — incapable of ever passing (false alarm) or ever failing (vacuous) — and the smoke-run above does not catch this, because it only proves the check *executes*, not that its verdict *tracks the input*. Real instance (loop 8b69e779): an awk formula that exited 1 unconditionally, so a genuine 39/39 pass and a genuine 18/40 fail produced identical exit codes and could never pass for any code state.

An eval may carry an optional `fixtures` object on top of the schema below:

```json
"fixtures": { "good": "<sample stdin that SHOULD pass>", "bad": "<sample stdin that SHOULD fail>", "formula": "<optional: the verdict-stage command; if absent, derived as the segment after the LAST top-level pipe in cmd>" }
```

When present, `scripts/post_evals.py validate-discriminating` pipes `fixtures.good` and `fixtures.bad` into the formula and requires opposite outcomes (good exits 0, bad exits non-zero) — rejecting the eval, by name, if both fixtures produce the same exit code (non-discriminating) or if the formula can't be reasonably derived from `cmd` (fail-closed, asks the author to supply `fixtures.formula` explicitly). The derivation splits on the last top-level pipe by text position, not shell syntax — a quoted pipe (e.g. inside an `awk` or `grep` pattern) forces `fixtures.formula` to be supplied explicitly, since the split would otherwise land inside the quoted string.

**Honest boundary, stated plainly:** this gate validates only checks that carry `fixtures`. Checks without `fixtures` are grandfathered — validated exactly as they were before this gate existed, with zero behaviour change. Adding `fixtures` to an eval is opt-in, never retroactive: freezing this gate does NOT retroactively validate any existing eval or evals.json that predates it, and an author who never adds `fixtures` gets no discrimination proof at all. And even where `fixtures` is present, a pass only proves the formula CAN discriminate between these two specific inputs — it proves nothing about whether the formula tests the RIGHT claim, whether `cmd` and `fixtures.formula` stay in sync after edits, or whether the fixtures themselves are representative. This gate closes the "never fails" class of defect; it is not a general correctness proof of the check.

## Verification level rules (self-exemption defence)

Concrete predicates, not vibes — same design rationale as agentic-loop Phase 2.6's "what named thing does this remove?" test for disposition.

- **Verification level 0 (exempt, justified):** single work-unit AND no outward/irreversible surface AND an existing test or verify-criterion already covers the goal state. The exemption is still a written artifact — the gates accept a justified exemption, never an absence. Anything rule 6 names — something a human sees or interacts with (a UI, CLI output, a rendered artifact, a served endpoint) — **is** an outward surface for this predicate: a user-facing change is minimum verification_level 1 and carries rule 6's ≥1 P0 drive-the-artifact eval. (This widens only the verification_level-0 test: verification_level 2's outward predicate stays scoped to its own parenthetical list — publish, deploy, migration, data deletion, external send — so user-facing alone does not escalate past verification_level 1.)
- **Verification level 1 (standard):** anything above verification_level 0 that doesn't meet a verification_level-2 predicate — 3–5 end-state evals, ≥1 negative control, P0/P1 split.
- **Verification level 2 (full suite):** ≥3 work-units (the line agentic-loop Phase 2.7/Phase 3 already draw) OR any irreversible/outward surface (publish, deploy, migration, data deletion, external send). Full suite with pre+post surfaces where applicable and the GO/NO-GO rule stated in the artifact.

`verification_justification` is required at every verification_level, not only verification_level 0: at verification_level 0 it states why the exemption is legitimate; at verification_level 1/2 it names which predicate fired (e.g. "2 work-units, no irreversible surface" or "≥3 work-units"). A blank justification is refused by the writer (`post_evals.py validate-structure`, check 2) at pr scope, and by the loop gates at loop scope — `loop_state_guard.py`/`loop_stall_guard.py` at completion and `loop_dispatch_guard.py` at dispatch, all three via `loop_evals.read_loop_evals` — the pr-scope MERGE reader itself only parses the posted marker comment (result/verification_level, no justification field), so enforcement there is entirely writer-side, at post time.

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

`new_cases[]` covers a third gap distinct from the other two amendment paths: a later independent review discovers the frozen suite is missing a case ENTIRELY — no eval was ever written for it because nobody anticipated it at freeze time. This differs from `amendments[]` (which edits an EXISTING eval id) and from `withdrawn_proofs` (a proof that ran and legitimately failed): here nothing was ever graded for the case until it was folded into an existing eval's `id`. Each `new_cases[]` entry's `id` must equal a real `.evals[].id` in the same file — `post_evals.py validate-structure` (check 11) refuses any entry whose `id` matches no `.evals[].id`, same posture as the other structural checks (non-zero exit, printed reason, no stamp written). Absent or empty `new_cases[]` is a no-op — most PRs never discover an uncovered case, and check 11 does not regress those files.

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

For agent-run evals, a fresh sonnet subagent is spawned to grade. Its prompt contains: the `evals.json` content, artifact references (PR number, clone path, artifact path or local endpoint, deployed surface), and the confidence-label contract — and explicitly nothing else. It must not receive the implementation conversation, the implementer's summary, or the orchestrator's opinion of the outcome — the same principle behind agentic-loop Phase 4b's clean-break gate (the author is the least able to see its own shims). The verifier returns per-eval status plus evidence; the orchestrator folds those statuses into `evals.json` — nothing more. Computing and stamping `result` is a separate, neutral step: `post_evals.py` for pr scope, `post_evals.py grade-loop` for loop scope. The orchestrator never writes `result` at either scope. Folding applies to fresh grader output only: an eval amended after a grader verdict goes back to a fresh grader, whose per-eval output is folded the same way, and the post-verdict amendment records who re-graded in a `regraded_by` field — `grade-loop` refuses to re-grade a post-verdict amendment that lacks it. `grade-loop` also stamps a `grading` object (`by`, a `checksum` over the per-eval statuses + result) that the loop-stop guard checks before accepting a GO/VERIFICATION_LEVEL0 verdict — honest boundary: the stamp catches accidental drift (a status edited after grading), not deliberate tampering. The stamp also records `amendments_at_grade`, which is what lets `grade-loop` detect a post-verdict amendment. The backstop's boundaries, stated plainly: it keys on amendment count growth after a grade-loop stamp. A status flipped with no accompanying amendment, an existing amendment edited or replaced in place, and a flip folded in before the first grade-loop run are all invisible to it, as is a hand-edited `amendments_at_grade` stamp (the stamp sits outside the checksum canon) — those cases are held by this rule and the Phase 13 audit alone. Amending means editing the graded file in place; regenerating the file sheds the stamp, and `grade-loop` treats remaining grade residue (`graded_at`/`result`) as the prior verdict, so a regenerated-but-residued file still refuses.
