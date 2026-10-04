# E3: authority objects (originally additive; now consumed by crack_on_gate, see the Superseded section)

## What the two crack-on gates enforce today

Read from source: `hooks/scripts/crack_on_gate.py` (88 lines) and `hooks/scripts/crack_on_prose_gate.py` (212 lines).
Reproduce: `sed -n 1,88p hooks/scripts/crack_on_gate.py; sed -n 1,60p hooks/scripts/crack_on_prose_gate.py`.

| Piece | Event | What it does | Evidence |
| --- | --- | --- | --- |
| `crack_on_gate.py` stamp | `UserPromptSubmit` | If the prompt matches `crack on` with no negation in the three words before it, writes the bare file `<CLAUDE_AGENTIC_LOOP_DIR or ~/.coderails/agentic-loop>/<session_id>/crack_on_active`. | `invoked()`, `stamp()`, `flag_path()` |
| `crack_on_gate.py` denial | `PreToolUse` on `AskUserQuestion` | Denies the tool while that flag file exists. | `main()` |
| `crack_on_prose_gate.py` | `Stop` | While the flag exists, blocks (exit 2) a final message that hands a question to the human (regex `MODAL` / `ASK_PATTERNS`), at most `CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS` (default 3) times per turn; skipped when `CODERAILS_HEADLESS_RUN=1`. | `match_question()`, `main()` |

Both key on `session_id` only. The flag is a bare file: no scope, no expiry, no revocation, no loop binding. Both
sanitise the id with `replace("/", "_").replace("..", "")`, so distinct ids can collide on one flag path. Neither
mentions merge: the "crack on never pre-authorises `/coderails:merge`" rule is a convention, not something either
gate enforces.

## What this change adds

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

## Superseded: crack-on grants and enforces through the authority object; the prose gate is retired

- `crack_on_gate.py` UserPromptSubmit: "crack on" (outside `"..."`/backticks, no negation in the three words before
  it) writes a 24h revocable object for the exact session id (scope `autonomous_decisions`, denied
  `destructive_shell`, `max_prs` 0, `merge` approval-required, `loop_id` from `CLAUDE_LOOP_ID`) and echoes it to the
  model. It calls `write_authority` directly because `authority.py create` refuses when a file exists, which would
  block re-granting after expiry.
- PreToolUse `AskUserQuestion`: denied only while `read_authority` returns a live object. Expired -> allowed and
  traced `authority_expired_allow`. Revoked/torn/foreign -> allowed (foreign traced by the library).
- Migration: a pre-existing `crack_on_active` flag (exact, path-safe id only) still denies, traced
  `crack_on_legacy_flag` with a message naming the `rm` that clears it. It is never converted to an object silently.
  Remove the fallback in the next release; the removal is a delete of `legacy_flag()` and its branch.
- `crack_on_prose_gate.py` (Claude and Codex) is deleted with its Stop registrations and tests. This is a
  LOOSENING: a final message that hands a question back in prose is no longer blocked under crack-on; only the
  `AskUserQuestion` / `request_user_input` tools are. The 4.9% block rate (5 of 103) in
  `docs/graph-alignment-measurement.md` is the cost of that retirement.
- Codex mirror: the package has no `scripts/lib`, so `hook_common.py` vendors a validator subset (exact session
  binding, unexpiry, merge approval-required). Storage is the shared loop dir, so one CLI revokes both providers.
- Reason codes: `authority_granted`, `authority_deny`, `authority_expired_allow`, `crack_on_legacy_flag` (command
  `crack_on`); `authority_refused_foreign` (command `authority`).

### Effect on a live running session

- (inferred, not run) A session already stamped keeps `AskUserQuestion` denied through the legacy path, with no
  expiry, until `rm <CLAUDE_AGENTIC_LOOP_DIR or ~/.coderails/agentic-loop>/<session_id>/crack_on_active`.
- (inferred) The prose Stop block stops once hooks reload. (guess) Claude Code may snapshot hooks at session start,
  so the old prose gate could persist until that session restarts; unknown.
- A new "crack on" in a running session writes `authority.json` (24h). Revoke:
  `python3 scripts/authority.py revoke --session <session_id>` (emits `authority_revoked`).
- Old Codex flags live under `$PLUGIN_DATA/sessions/<id>/crack_on_active` (a different directory); clear that path.
