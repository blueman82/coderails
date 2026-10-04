# E3: authority objects (additive, nothing consumes them yet)

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

## What it deliberately does not do

- Neither gate reads the object; their behaviour is unchanged (their existing tests run unmodified).
- The crack-on stamp does not create an object (negative control: `authority_test.py::test_crack_on_stamp_does_not_create_authority`). An
  object exists only when someone runs `scripts/authority.py create`, so "crack on" prose grants nothing new.
- The prose gate is not retired. That governs the live autonomy envelope and needs the user's sign-off after the
  object has run in practice.
- `read_authority` has no consumer; wiring a gate to it is a separate change.
