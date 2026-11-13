# E3: authority objects (originally additive; now consumed by crack_on_gate, see the Superseded section)

## What the two crack-on gates enforce today

The historical source was `hooks/scripts/crack_on_gate.py` (88 lines) and `hooks/scripts/crack_on_prose_gate.py` (212 lines).
To reproduce, run `sed -n 1,88p hooks/scripts/crack_on_gate.py; sed -n 1,60p hooks/scripts/crack_on_prose_gate.py`.

| Piece | Hook | Behavior | Source |
| --- | --- | --- | --- |
| `crack_on_gate.py` stamp | `UserPromptSubmit` | If the prompt has `crack on` with no negation in the three words before it, the hook writes `<CLAUDE_AGENTIC_LOOP_DIR or ~/.coderails/agentic-loop>/<session_id>/crack_on_active`. | `invoked()`, `stamp()`, `flag_path()` |
| `crack_on_gate.py` denial | `PreToolUse` on `AskUserQuestion` | The hook denies the tool if it finds the flag file. | `main()` |
| `crack_on_prose_gate.py` | `Stop` | If there is a flag file, the hook can block a last message that gives a question to the human. It exits 2 and uses regex `MODAL` or `ASK_PATTERNS`. It blocks up to `CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS` times for each turn (default 3). It skips `CODERAILS_HEADLESS_RUN=1`. | `match_question()`, `main()` |

The two hooks use `session_id` only. The flag file has no scope, expiry, revocation, or loop binding.
The hooks change the ID with `replace("/", "_").replace("..", "")`, so two different IDs can use the same path.
The two gates do not check merges. The rule "crack on never pre-authorises `/coderails:merge`" was a convention.

## What this change adds

- The `scripts/lib/authority_object.py` module has pure `validate(obj, now)`, `read_authority(session_id, dir)`, and atomic `write_authority` (tmp and `os.replace`).

- The `scripts/authority.py` commands are `create`, `inspect`, `narrow`, and `revoke`.
  The object is at `<dir>/<session_id>/authority.json`, in the same directory as the flag.
  It can have a null `loop_id`.

- The object has `authority_id`, `loop_id`, `session_id`, `scope`, and `denied`. Its other fields are `max_prs`, `expires_at`, `revocable`, and `approval_required_for`.
  The validator requires `merge` in `approval_required_for`.

- The `narrow` command can only shrink `scope` or decrease `max_prs`. A non-revocable object cannot be revoked.

- The reader refuses session IDs with `/` or `..` and does not change them.
  The `read_authority` function gives an object only for the ID in that object. A different ID gives `authority_refused_foreign` and a log entry.

- The diagnostic codes are `authority_created`, `authority_narrowed`, `authority_revoked`, and `authority_refused_foreign`.

## What it deliberately did not do (SUPERSEDED, see below)

The initial change kept the two gates and did not let the crack-on stamp make an authority object.
It kept the prose gate pending owner approval after live use. The `read_authority` function had no caller.
The next section supersedes these four decisions. The user directed retirement.

## Superseded: crack-on grants and enforces through the authority object; the prose gate is retired

- In UserPromptSubmit, `crack_on_gate.py` writes a 24h revocable object for the matching session ID when the phrase check succeeds.
  The phrase is "crack on" in text without `"..."` or backticks around it.
  The three preceding words must have no negation such as `don't`, a word ending in `n't`, `not`, `never`, or `avoid`.
  The phrase cannot precede a `?` in the same sentence.

  The object uses scope `autonomous_decisions`, denied `destructive_shell`, `max_prs` 0, and mandatory approval for `merge`.
  It uses `loop_id` from `CLAUDE_LOOP_ID` and reports the object to the model.
  The hook uses `write_authority` directly. The `authority.py create` command refuses if there is a file and could block a new grant after expiry.

- PreToolUse denies `AskUserQuestion` only while `read_authority` gives a live object. An expired object lets it through and logs `authority_expired_allow`.
  A revoked object or one from a different session lets it through. The library logs the different session.

  An unparseable value or a value that is not an object gives no authority. The hook logs `authority_corrupt_ignored` and continues.
  A legacy flag continues to apply if found.

- A previous `crack_on_active` flag for the same path-safe ID continues to deny and logs `crack_on_legacy_flag`.
  The message gives the `rm` command to clear it. The hook does not turn it into an object automatically.
  The next release can remove the fallback by removing `legacy_flag()` and its branch.

- The change removes `crack_on_prose_gate.py`, Stop registration, and tests for Claude and Codex.
  It no longer blocks a last message that asks the human a question in prose. It blocks only the `AskUserQuestion` and `request_user_input` tools.
  The 4.9% block rate (5 of 103) in `docs/graph-alignment-measurement.md` measures the cost of retirement.

- The Codex package has no `scripts/lib` at this point. The `hook_common.py` file includes a subset of the validator.
  It checks session ID, expiry, and mandatory approval for merge. One CLI revokes authority for the two providers because they share the loop directory.

- The `crack_on` codes are `authority_granted`, `authority_deny`, `authority_expired_allow`, `crack_on_legacy_flag`, and `authority_corrupt_ignored`.
  The `authority` command also logs `authority_refused_foreign`.

### Effect on a live running session

- (inferred, not run) A session with the legacy flag keeps `AskUserQuestion` denied without expiry.
  Clear it with `rm <CLAUDE_AGENTIC_LOOP_DIR or ~/.coderails/agentic-loop>/<session_id>/crack_on_active`.

- (inferred) The prose Stop block stops after the hooks reload.
  (guess) Claude Code can snapshot hooks at session start. The previous prose gate can stay until the session starts again. This is unknown.

- A new "crack on" in a live session writes `authority.json` with a 24h expiry.
  Revoke with `python3 scripts/authority.py revoke --session <session_id>`. The command logs `authority_revoked`.

- Previous Codex flags use `$PLUGIN_DATA/sessions/<id>/crack_on_active`. Clear that path for Codex.

## Action receipts (roadmap item 3): approval bound to one exact action

The receipt has its own schema. The authority object expires, has a session scope, and rejects unknown keys in `validate()`.
Keeping the schemas apart avoids coupling them.
The library is `scripts/lib/action_receipt.py` (standard library, Python 3.9). The CLI is `scripts/action_receipt_cli.py approve-action | inspect-receipt | revoke-receipt`.

Each receipt is one write-once JSON file at `<loop dir>/<session>/receipts/<receipt_id>.json`. The writer uses tmp and `os.replace`.
Consume and revoke use `<id>.consumed` and `<id>.revoked` marker files made with `O_CREAT|O_EXCL`.

The file determines single-use status. The writer does not use a read-modify-write step. A torn write cannot consume only part of the receipt.
A truncated receipt gives `malformed` and is refused.

The pure `verify(receipt, proposed, now, session_id, loop_id, consumed, signers)` function gives `(ok, reason_code)`.
It checks `malformed` first. Then it checks the signature for `signature_missing`, `signature_invalid`, `signer_unknown`, or `trust_root_missing`.
The sequence continues with `revoked`, `expired`, `foreign_session`, `foreign_loop`, `consumed`, and `kind_mismatch`.
It then checks `hash_mismatch`, `repository_mismatch`, `ref_mismatch`, and `sha_mismatch`. With no error, it gives `ok`.

The SHA-256 hash uses canonical JSON of the shlex-split command, cwd, branch, repository, and ref.
A v2 receipt is signed, bound to repository, ref, and SHA, and single-use. The `artifact_sha` field is mandatory.
The verifier refuses v1 and unsigned receipts. See [p3-human-only-minting.md](p3-human-only-minting.md).

Claude appends `action_authority_gate.py` to the Bash group.
Codex imports copies of `scripts/lib/{action_receipt,receipt_signing,action_binding}.py` with the same bytes.
The `action_authority` values are `enforce`, `advisory`, and `off`. The default is `enforce`.
The change does not edit `pr_merge_gate`, the destructive gate, or `enforce_pr_workflow`.

A receipt shows that a key in the user-tier signers file signed the binding for this session and loop. The binding includes command text, cwd, branch, repository, ref, and SHA.

It expires and works one time. The `approve-action` command refuses without a tty (`receipt_refused_no_tty`).
The agent can edit the user-tier signers file. This is a cooperating-agent safeguard. It cannot prove human approval.

The hash uses only the command text that the hook sees. The hook unwraps usual wrappers but does not see aliases, functions, or eval/xargs.
The check protects only `main` and `master`.
The `agent_only_gate` probe and a payload test show subagents with the same `session_id` but different `agent_id` or `agent_type`.
Thus a subagent can use its parent's receipt.

The `scripts/merge.py` helper cannot see shell command text. With no hook run, it checks the signed hash against a canonical command.
That command is `python3 scripts/merge.py <target> --expected-head <sha>`, with cwd, branch, repository, and ref.
The target is the PR number, branch name, or `auto` argument the caller gives.
The hook must have consumed the receipt in the last 300 s.
The user can edit `action_authority: off` and the user-tier trust root, so the same-user limit applies.

The typed statuses are `NEEDS_DECISION | OUTSIDE_SCOPE | IRREVERSIBLE_ACTION`.
The standalone validator is `skills/agentic-loop/scripts/worker_status.py`. The Codex copy has the same bytes.
The two `record_wave` paths run `worker_status.prepare()` before the pure core.
A typed status consumes one retry and writes one typed Stop row in the same locked write.

A `done` result with `final_report_required` must have a correct `final_report` structure. The worker supplies its content.
Orchestrator confidence and verify lints stay advisory.

### Passphrases and default enforcement

The 24 October owner revision made passphrases optional. Signed receipts remain mandatory in default `enforce` mode.
The gate, example settings, and init settings default to `enforce` with or without a config file.
An incorrect config causes refusal. Explicit `advisory` warns and explicit `off` disables the receipt gate.
The project can keep its explicit override.

The owner issues each `approve-action` at their controlling terminal.
A key without a passphrase or an available agent-backed key can sign without a prompt.
An autonomy grant does not replace the receipt. A `merge.py` call also uses `--expected-head <sha>` to make a binding for the merge.
PR inspection, eval, and integrity gates continue to control merges.

## Superseded again: grant moves off prose matching to a typed command

The change removes about 45 lines of phrase checks: `invoked()`, negation, questions, and quotes.
The check `invoked("do not, under any circumstances, crack on")` gave `True`. Negated text and text copied into a prompt could mint authority.

- The `scripts/authority.py grant --session <id> --max-prs N [--loop --scope --denied --expires-in-hours --approval-for]` command writes `granted_by: command`.
  It logs `authority/granted/authority_granted_command`. The `create` alias uses the same path for one release.
  Merge approval stays mandatory. A live object causes `authority_refused_exists`. The command can replace an expired or torn file.

- The optional `granted_by` field in `scripts/lib/authority_object.py` accepts `command` or `legacy_phrase`.
  Other values fail `validate`. Objects without the field read as `legacy_phrase` until expiry. Other `FIELDS` stay closed.

- The `commands/authorize.md` command (`/coderails:authorize`, `disable-model-invocation: true`) runs the grant before the model sees it.
  It uses `--session "${CLAUDE_SESSION_ID}"` and fixed defaults: scope `autonomous_decisions`, denied `destructive_shell`, and `max_prs` 0.
  It does not put user text in the `!` command. A test forbids `$ARGUMENTS` there.
  For different limits, run the CLI directly. The script uses `$CLAUDE_CODE_SESSION_ID` if expansion gives an empty value.
  Codex `packages/codex/skills/authorize/SKILL.md` gives the same command without pre-execution.

- The Claude and Codex `crack_on_gate.py` hook does not write on `UserPromptSubmit`.
  For "crack on" or "crack-on" with no live authority, it adds `additionalContext` with the grant command.
  It logs `crack_on/ignored/authority_phrase_ignored`.
  Denial for `AskUserQuestion` and `request_user_input`, expiry, revocation, different session, and legacy-flag behavior stay unchanged.

  The subsequent B3 correction makes each hook check for `autonomous_decisions` in the grant scope.
  The printed grant command includes that scope and `--denied destructive_shell`.
  A narrowed grant with an empty scope lets user input through.

- The `packages/codex/scripts/authority.py` and `packages/codex/scripts/lib/authority_object.py` copies have the same bytes as Claude, as the parity test checks.
  The `hook_common.py` file imports the copied library. It no longer includes `authority_state`, `write_authority`, or `parse_expiry`.
  The diagnostic log and authority paths use `CODERAILS_AGENTIC_LOOP_DIR` as a fallback, as the previous Codex copy did.

- A session ID starts with an ASCII letter or digit. Subsequent characters can be ASCII letters, digits, `.`, `_`, or `-`.
  The ID cannot contain `..`. The grant CLI and hook in each provider check the ID. Other characters cannot enter a printed shell command.

- The typed command prevents accidental grants from negated text or text copied into a prompt.
  An agent with shell access can run `authority.py grant`, and the Codex skill instructs it to do so.
  This is a cooperating-agent safeguard. Optional signed receipts use their own mechanism.

- The `granted_by` field is unsigned and self-asserted. A same-user agent can write `authority.json` directly with Write or shell redirection.
  It can supply a different value or no value. It can also set the legacy `crack_on_active` flag, which has no expiry and applies in this historical version.
  The paths have no write guard. The crack-on hint tells agents that grants belong to the user.

- The sequence of `${CLAUDE_SESSION_ID}` substitution and `!` pre-execution is unverified on Claude Code 2.1.289.
  Binary strings show substitution in the skill body. The tests did not show the shell execution sequence.
  The environment fallback handles an empty expansion. The implementation does not use the planned UserPromptSubmit prefix-match fallback.

- Live probe on 2026-10-05: The non-interactive build session could not run `/coderails:authorize`.
  Substitution and `!` sequence remain unverified. The Claude tool environment exports `CLAUDE_CODE_SESSION_ID`, the fallback source.

  The `grant` command refuses IDs with `$` or `{`, such as a literal `${CLAUDE_SESSION_ID}` after a substitution error.
  It also refuses an empty ID with the environment setting unset.
  The refusal gives `authority_refused_unsafe_session` and writes nothing. See `scripts/tests/authority_session_guard_test.py`.
  To close the live check, run `/coderails:authorize` one time in a live session and check that the result names its actual ID.

## Current naming — PR #561

[PR #561](https://github.com/blueman82/coderails/pull/561) renames the owner entry points to `/coderails:authorise` (`commands/authorise.md`) and `$coderails-codex:authorise` (`packages/codex/skills/authorise/SKILL.md`).
The word `autonomous` shows a hint through `autonomous_gate.py` and grants no authority.
The earlier authorize and crack-on descriptions are historical.

With the optional receipt gate off, usual PR work uses no receipt, key, or passphrase.
Explicit `enforce` continues to use signed receipts. The inspection, eval, and integrity gates stay in force.

## Legacy reader retirement — PR #562

[PR #562](https://github.com/blueman82/coderails/pull/562) retires the previous flag readers, optional or missing stamps, `legacy_phrase` stamps, and the `authority.py create` alias.
The change does not automatically edit, migrate, relabel, or remove saved flag files and legacy authority objects.
They no longer give authority. Owners use the current `authorise` entry points and typed `grant` to issue a new grant.

The break removes denied-operation restrictions, max-PR caps, authority-derived loop binding, and advisory merge-budget reservation for rejected legacy objects.
This uses the existing branches for no authority. The change can relax those controls and cannot prove approval from a human who acts independently.
Optional receipt-off behavior and the inspection, eval, and integrity gates stay the same.
Typed grants keep session binding, expiry, and revocation.

Live saved data and the existence of external clients remain unknown. Historical descriptions above record their previous behavior.
