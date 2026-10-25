# Muninn is the authoritative typed-memory store (default on)

## Decision

`scripts/lib/memory_adapter.py` (the #496 adapter) is no longer an optional helper. Muninn schema v2 is the only typed
memory store and it is on by default: config key `memory.backend: muninn|off` (default `muninn`, `enforced_by_code`,
read through `scripts.lib.config.config_path` / `config_value(section=memory)`).

- Missing, old, schema-v1, locked or refusing Muninn gives a reason-coded `Degraded` (CLI exit 3, reason on stdout, a
  `memory.<op>` trace row). Nothing is written anywhere else: no Markdown, no side ledger.
- `memory.backend: off` is the only no-Muninn mode. It is explicit and traced (`memory_backend_off`); it also never
  reads or writes Markdown. Any other value gives `memory_backend_invalid`.
- `probe()` checks, in order: the backend switch, muninn on PATH, the Part A `--help` flags, the store schema through
  `memory_schema.check` (reads `PRAGMA user_version` and the typed columns, never `muninn --version`), and one read
  smoke (`know list --scope-loop memory-probe --status all`).
- `add()` returns `Written(id='K<n>')` or `Degraded`. A Muninn refusal (rc 2, `{"error": c}`) becomes `refused_<c>`;
  other nonzero exits stay `muninn_error`. The reason-code table lives in `scripts/lib/memory_reasons.py` and
  `docs/RUNBOOK.md` ("Memory degraded (Muninn authoritative)"); a test requires every code to appear there.
- Markdown (`MEMORY.md`, standing orders, handoff text) is a generated read-only view through `write_view`, which only
  overwrites an absent or marker-stamped file.

## Cites are user-anchored

Muninn refuses a short approval prompt cited alone (`approval_needs_reply`) and an agent cannot cite its own
conclusions. `scripts/lib/memory_cite.py` therefore accepts two forms, both anchored in a user prompt:

1. `quote_only`: a substantive quote of a user prompt, 12 to 300 characters after whitespace collapse (shorter with no
   ref is `cite_too_short`). With no ref Muninn finds the caller session's own prompt.
2. `approved_reply`: the proposing reply plus the user's approval prompt, resolved from `muninn session <root>` with
   role and kind verified (`--approval REF` on the CLI).

A cite set without a user-prompt anchor is `cite_not_user`, decided before Muninn is spawned. Agent decisions are
stored with `confidence=inferred`; Muninn marks them pull-only, which is correct.

## Limits (stated, not hidden)

- Orchestrator-only writes: subagent threads are not citable, so only the orchestrator session can write typed records
  (`refused_not_citable`). Workers hand their lesson text to the orchestrator.
- User-anchored cites: a lesson the owner never said in a prompt cannot be recorded unless the owner approves it. The
  degrade is reason-coded (`cite_not_user`, `refused_approval_needs_reply`); it is never silently replaced by Markdown.
- Cooperating-agent boundary: library callers declare the cite role; the CLI verifies it from the session. Muninn
  re-verifies every quote against the transcript, but a caller that lies about a ref it controls is not stopped. This
  is a cooperating-agent safeguard, not a security boundary.
- Own session only: the CLI resolves every add (quote-only too) from `muninn session <caller session id>`. A cite ref
  in another session is `cite_not_own_session`; a quote-only quote must sit inside a user prompt of the caller's
  session (else `cite_not_user`); an approval must be a prompt of 80 chars or fewer directly after the reply
  (`cite_bad_approval`). The library default for `Record.cite_role/cite_kind` is empty (`cite_not_user`), so a
  programmatic caller must declare the anchor. Not stopped: text an agent injected that the transcript records as a
  user prompt of the caller's own session (hook or tool output), and an approval that is short and adjacent but about
  something else (the claim is not bound to the reply text).
- Same-user boundaries: the agent can run `muninn know add|retract` directly, bypassing the adapter (readers only check
  a non-empty cite and quote, not the anchor), and can set `memory.backend: off` in the workflow config. The off switch
  is visible (`memory_backend_off` degrade and a trace row) but not gated. No Bash-gate denial for direct muninn writes
  is built; this is not a security boundary.
- Supersede and contradict: `--supersedes`/`--contradicts` must be `K<n>` (`bad_record` otherwise). Muninn itself
  refuses a supersede across scopes (`refused_bad_supersedes`); inside one scope a user-quoted record can retire a
  standing order, which is intended. `list_records` keeps only entries of the requested scope (global for `user`).
- Contract parity: `scripts/tests/muninn_contract_test.py` runs the same scenario table against the real `muninn`
  (temp `MUNINN_HOME`, `MUNINN_ROOTS`, `HOME`) and the sqlite fake, so the fake cannot drift unnoticed. It is skipped,
  with a message, only when `muninn` is not on PATH or lacks the Part A flags. It never touches the live store.

## Handoff notes

- Muninn side (separate repo, not edited here): `muninn session` prints `preview` (maybe truncated) instead of full
  text; a `--json` text field would let reply quotes always be exact. A fresh machine has no store until
  `muninn ingest`; `know list` on a missing store exits 4 `store_unavailable`, reported as `muninn_store_missing`.
