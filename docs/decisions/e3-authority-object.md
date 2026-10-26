# E3: authority object history and the current autonomous command

This page records several earlier designs. The old hook names and commands below are historical evidence.
For the current source behavior, read [Current behavior](#current-behavior-26-october-2026).
Source behavior does not prove that installed plugins use this version.

## Historical state: phrase hooks before authority objects

The original design read `hooks/scripts/crack_on_gate.py` and `hooks/scripts/crack_on_prose_gate.py`.
Those paths are no longer active. The table records what the hooks did at that time.

| Piece | Event | What it did | Evidence |
| --- | --- | --- | --- |
| `crack_on_gate.py` stamp | `UserPromptSubmit` | Wrote `<CLAUDE_AGENTIC_LOOP_DIR or ~/.coderails/agentic-loop>/<session_id>/crack_on_active` when the prompt matched `crack on` without negation in the three preceding words. | `invoked()`, `stamp()`, `flag_path()` |
| `crack_on_gate.py` denial | `PreToolUse` on `AskUserQuestion` | Denied the tool while that flag file existed. | `main()` |
| `crack_on_prose_gate.py` | `Stop` | Blocked a final message that handed a question to the human while the flag existed. It used `MODAL` / `ASK_PATTERNS` and allowed at most three blocks per turn. It skipped the check when `CODERAILS_HEADLESS_RUN=1`. | `match_question()`, `main()` |

Both keyed on `session_id` only. The flag was a bare file with no scope, expiry, revocation, or loop binding.
Both sanitised the id with `replace("/", "_").replace("..", "")`, so distinct ids could collide on one flag path.
Neither hook checked merge approval. That rule was a convention.

## Original authority object addition (historical)

- `scripts/lib/authority_object.py`: pure `validate(obj, now)`, `read_authority(session_id, dir)`, atomic
  `write_authority` (tmp + `os.replace`).
- `scripts/authority.py`: `create`, `inspect`, `narrow`, `revoke`. Stored at `<dir>/<session_id>/authority.json`,
  the same per-session directory as the flag (with or without a loop; `loop_id` is nullable).
- Fields: `authority_id`, `loop_id`, `session_id`, `scope`, `denied`, `max_prs`, `expires_at`, `revocable`,
  `approval_required_for`.
- `approval_required_for` always contains `merge`; the validator rejects any object without it.
- `narrow` only shrinks `scope` (subset) or `max_prs` (lower). A non-revocable object cannot be revoked.
- Session ids containing `/` or `..` are refused, never sanitised. `read_authority` returns the object only for the
  exact id it embeds; a mismatch is refused and traced (`authority_refused_foreign`).
- Trace reason codes: `authority_created`, `authority_narrowed`, `authority_revoked`, `authority_refused_foreign`.

## What it deliberately did not do (SUPERSEDED, see below)

The original change kept both gates untouched, did not let the crack-on stamp create an object, did not retire the
prose gate (that needed the user's sign-off after the object had run in practice), and left `read_authority` without
a consumer. Those four lines are superseded by the next section; the user directed the retirement.

## Earlier phrase grant through authority objects (superseded)

This section records the former phrase grant. It is not the current input gate.

- `crack_on_gate.py` on `UserPromptSubmit` wrote a 24-hour revocable object for a `crack on` prompt.
  It ignored quoted text, backticks, negation in the three prior words, and questions in the same sentence.
  It used the exact session id, scope `autonomous_decisions`, denied
  `destructive_shell`, `max_prs` 0, required merge approval, and took `loop_id` from `CLAUDE_LOOP_ID`.
  It called `write_authority` directly to allow a grant after expiry.
- `AskUserQuestion` was denied while `read_authority` returned a live object. Expired, revoked, foreign, or corrupt
  objects did not cause that denial. The old flag could still cause denial. The hook traced each reason.
- A pre-existing `crack_on_active` flag still denied input then, with reason `crack_on_legacy_flag`.
  It was not converted into an authority object. The follow-up below removed this reader.
- `crack_on_prose_gate.py` (Claude and Codex) was deleted with its Stop registrations and tests.
  That change allowed a final message with a question in prose. It left the `AskUserQuestion` /
  `request_user_input` tool gate. The measured prose block rate was 4.9% (5 of 103) in
  `docs/graph-alignment-measurement.md`.
- The Codex package had no `scripts/lib` then, so `hook_common.py` included a validator subset.
  Storage used the shared loop directory, so one CLI revoked both providers.
- Reason codes: `authority_granted`, `authority_deny`, `authority_expired_allow`, `crack_on_legacy_flag`, `authority_corrupt_ignored` (command
  `crack_on`); `authority_refused_foreign` (command `authority`).

### Historical effect on a running session

- (Inferred, not run at that time) A stamped session would have kept `AskUserQuestion` denied through the old flag path
  until the flag was removed. That path had no expiry.
- (Inferred at that time) The prose Stop block would have stopped after hooks reloaded. Whether Claude Code kept
  the old hook until session restart was unknown.
- At that time, a new phrase grant wrote `authority.json` for 24 hours. The revoke command was
  `python3 scripts/authority.py revoke --session <session_id>` (emitted `authority_revoked`).
- Old Codex flags lived under `$PLUGIN_DATA/sessions/<id>/crack_on_active`.

## Action receipts (roadmap item 3): approval bound to one exact action

- Separate schema, not authority-object fields: `validate()` rejects unknown keys and the authority object is
  expiring and session-scoped, so mixing them would couple the schemas. Library `scripts/lib/action_receipt.py`
  (stdlib, py3.9), CLI `scripts/action_receipt_cli.py approve-action | inspect-receipt | revoke-receipt`.
- Storage: one write-once JSON per receipt at `<loop dir>/<session>/receipts/<receipt_id>.json` (tmp + `os.replace`,
  never rewritten). Consume and revoke are `<id>.consumed` / `<id>.revoked` marker files created with
  `O_CREAT|O_EXCL`, so single-use state is file existence: no read-modify-write race, and a torn write cannot
  half-consume (a truncated receipt reads as `malformed` and is never accepted).
- `verify(receipt, proposed, now, session_id, loop_id, consumed, signers)` is pure and returns `(ok, reason_code)`; check order is fixed:
  `malformed`, signature (`signature_missing`, `signature_invalid`, `signer_unknown`, `trust_root_missing`), `revoked`, `expired`,
  `foreign_session`, `foreign_loop`, `consumed`, `kind_mismatch`, `hash_mismatch`, `repository_mismatch`, `ref_mismatch`,
  `sha_mismatch`, else `ok`. The hash is sha256 of canonical JSON of the shlex-split command, cwd, branch, repository and ref.
  Receipts are v2: signed, bound to repository+ref+SHA (`artifact_sha` is mandatory), always single-use; v1/unsigned receipts
  are rejected with no downgrade path. See [p3-human-only-minting.md](p3-human-only-minting.md).
- Hook `action_authority_gate.py` (Claude, appended to the Bash group; Codex imports the byte-identical mirrored
  `scripts/lib/{action_receipt,receipt_signing,action_binding}.py`): opt-in via config `action_authority` (enforce | advisory | off, default off); it does not touch
  `pr_merge_gate`, the destructive gate or `enforce_pr_workflow`.
- What a receipt proves: a key listed in the user-tier signers file signed this command text, cwd, branch,
  repository, ref and SHA for this session and loop. It expires and can be used once. `approve-action` refuses
  without a tty (`receipt_refused_no_tty`). The user-tier signers file is agent-writable, so this is a
  cooperating-agent safeguard. It does not establish independent human approval.
- Limits: hash covers only the command text the hook sees (not aliases, functions, eval/xargs; common wrappers are
  unwrapped); protected branches are main/master only. Subagent identity is settled by the `agent_only_gate` evidence (same `session_id`, differing `agent_id`/`agent_type`) and a payload test, so the parent's
  receipt is honoured by a subagent. `scripts/merge.py` cannot see the shell's command text; when no hook ran it checks the signed hash against the canonical `python3 scripts/merge.py <target> --expected-head <sha>` command, cwd, branch, repository and ref. The target is the PR number, branch name, or `auto` argument supplied to the helper. A hook-consumed receipt must be
  within 300 s. `action_authority: off` and the user-tier trust root are agent-writable: cooperating-agent safeguard, not a boundary.

- Worker statuses `NEEDS_DECISION | OUTSIDE_SCOPE | IRREVERSIBLE_ACTION` ship as a standalone validator
  (`skills/agentic-loop/scripts/worker_status.py`, Codex copy byte-identical). Both providers' `record_wave` now call
  `worker_status.prepare()` before the pure core, so typed statuses consume one retry and write one typed stop row in
  the same locked write. A `done` result with `final_report_required` needs a valid `final_report`; its content remains
  worker supplied. Orchestrator confidence and verify lints remain advisory.

### Owner revision, 24 October 2026

The shipped workflow config sets `advisory`. With no config or an unknown value, the gate is off. Routine pushes and merges do not need a key or passphrase. Explicit `enforce` requires a signed receipt. A direct `merge.py` call also needs `--expected-head <sha>` to bind that receipt. PR review, eval, and integrity gates still govern merges.

## Earlier typed grant with legacy readers (superseded)

This section records the next source version. The final section gives the current source behavior.

The phrase heuristics (`invoked()`, negation, question and quote handling, about 45 lines) are deleted. Verified defect:
`invoked("do not, under any circumstances, crack on")` returned True, so negated and pasted text could mint authority.

- Mint: `scripts/authority.py grant --session <id> --max-prs N [--loop --scope --denied --expires-in-hours --approval-for]`
  wrote `granted_by: command` and traced `authority/granted/authority_granted_command`. `create` was a one-release alias.
  Merge approval stayed mandatory. A live object was not replaced (`authority_refused_exists`); an expired or torn file was.
- `scripts/lib/authority_object.py` allowed `granted_by` in `{command, legacy_phrase}` and refused other values.
  Old objects without the field read as `legacy_phrase` and remained valid until expiry. `FIELDS` stayed closed otherwise.
- `commands/authorize.md` (`/coderails:authorize`, `disable-model-invocation: true`) pre-executed the grant with
  `--session "${CLAUDE_SESSION_ID}"` and fixed defaults (scope `autonomous_decisions`, denied `destructive_shell`, `max_prs` 0).
  It did not splice user text into the `!` command. Other limits required the CLI. The script used
  `$CLAUDE_CODE_SESSION_ID` if the expansion was empty.
  Codex: `packages/codex/skills/authorize/SKILL.md` instructed the same command (no pre-execution).
- `crack_on_gate.py` (Claude and Codex) did not write on `UserPromptSubmit`. The old phrase printed a grant hint and
  traced `crack_on/ignored/authority_phrase_ignored`. The input gate still read legacy flags at that time.
  A later correction checked for `autonomous_decisions` in the grant scope. An empty scope allowed user input.
- Codex mirror: `packages/codex/scripts/authority.py` and `packages/codex/scripts/lib/authority_object.py` matched
  the Claude files byte for byte (parity test). `hook_common.py` stopped carrying its own authority validator
  and imported the mirrored library. Trace and authority paths used `CODERAILS_AGENTIC_LOOP_DIR` as a fallback.
- A session ID had to start with an ASCII letter or digit. It could then contain ASCII letters, digits, `.`, `_`,
  or `-`, but not `..`. Both grant CLIs and both hooks used this check.
- Limit (cooperating-agent safeguard): an agent with shell access can also run `authority.py grant` (for Codex the skill is itself an
  instruction to do so). The change stopped accidental, negated, and pasted-text grants. It did not stop a hostile
  same-user agent. Optional signed receipts were a separate unit.
- Same-user boundary at that time: `granted_by` was an unsigned, self-asserted label. An agent could run `grant`, write `authority.json`, or touch a legacy `crack_on_active` flag. The old flag still caused denial then. The hint told agents not to grant.
- Not verified: that `${CLAUDE_SESSION_ID}` is substituted before the `!` pre-execution runs in Claude Code 2.1.289 (strings in the binary show
  substitution in the skill body, ordering vs shell execution not observed); the env fallback covers an empty expansion. The
  UserPromptSubmit prefix-match fallback named in the plan was not built.
- Live-probe record (2026-10-05): a live `/coderails:authorize` run could not be made from the non-interactive build session, so the
  substitution and `!` ordering stay unverified. What is verified: the tool environment of a Claude session exports
  `CLAUDE_CODE_SESSION_ID` (the fallback source), and `grant` now refuses any session id containing `$` or `{` (a literal
  `${CLAUDE_SESSION_ID}` from a failed substitution) or an empty id with the env var unset, each with
  `authority_refused_unsafe_session` and nothing written (`scripts/tests/authority_session_guard_test.py`). A failed substitution
  therefore failed loudly instead of reporting a grant no hook could see. The live command check remained open at that time.

## Current behavior, 26 October 2026

This source revision uses `autonomous_gate.py` for both providers. The user command is `/coderails:authorise`.
It grants authority through `scripts/authority.py grant`. The word `autonomous` only prints a hint.
The source removes the one-release readers. A valid authority object needs `granted_by: command`.
Objects without that field, or with `legacy_phrase`, grant nothing. The `create` alias no longer runs.
The Claude and Codex `autonomous_gate.py` hooks ignore old `crack_on_active` flags. Grant and revoke leave those files on disk.
The file check before this source change found 255 loop session directories, no authority objects, and two old flags.
The Codex plugin data directory had no sessions. This check does not prove that installed plugins use this source.
Release acceptance requires another retained-state check, both provider installs, and live `authorise` and revoke tests.
