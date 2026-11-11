# Muninn is the authoritative typed-memory store (default on)

## Decision

Muninn schema v2 is the only typed memory store. It is on by default. The adapter is `scripts/lib/memory_adapter.py` from #496.
The config key is `memory.backend: muninn|off`. Its default is `muninn` and its category is `enforced_by_code`.
The adapter reads it through `scripts.lib.config.config_path` and `config_value(section=memory)`.

- The adapter gives `Degraded` if it cannot find Muninn. It gives the same result for an outdated store, a schema v1 store, or a locked store. It also gives `Degraded` if Muninn refuses an operation.
  The CLI exits with code 3, gives the cause on stdout, and writes a `memory.<op>` diagnostic log entry. There is no Markdown write or side ledger.

- `memory.backend: off` is the only mode without Muninn. Set it explicitly. The adapter logs `memory_backend_off`.
  This mode does not read or write Markdown. An unrecognized value gives `memory_backend_invalid`.

- `probe()` checks the backend switch, then looks for muninn on PATH, then checks the Part A `--help` flags.
  It checks the store schema through `memory_schema.check`, which reads `PRAGMA user_version` and the typed columns.
  It does not use `muninn --version`. It runs one read check with `know list --scope-loop memory-probe --status all`.

- `add()` gives `Written(id='K<n>')` or `Degraded`. A Muninn refusal (rc 2, `{"error": c}`) becomes `refused_<c>`.
  Other nonzero exits give `muninn_error`. See the table in `scripts/lib/memory_reasons.py` and "Memory degraded (Muninn authoritative)" in `docs/RUNBOOK.md`.
  A test checks that each code appears there.

- `write_view` writes read-only Markdown views for `MEMORY.md`, standing instructions, and handoff text.
  It writes a new file or overwrites a file with the marker.

## Cites are user-anchored

Muninn refuses a short approval prompt cited alone (`approval_needs_reply`). An agent cannot cite its own inference.
The two cite types in `scripts/lib/memory_cite.py` use a user prompt as an anchor:

1. `quote_only`: a substantive quote from a user prompt. It has 12 to 300 characters after whitespace collapse.
   A shorter quote without a ref gives `cite_too_short`. With no ref, Muninn finds the prompt in the caller's session.
2. `approved_reply`: the reply with the proposal plus the user's approval prompt. The source is `muninn session <root>`.
   The reader checks role and type. The CLI uses `--approval REF`.

If the cite set has no anchor in a user prompt, the adapter gives `cite_not_user` before it starts Muninn.
It keeps agent decisions with `confidence=inferred`. Muninn marks them pull-only.

## Limits (stated, not hidden)

- Only the orchestrator session can write typed records. Subagent threads cannot be cited (`refused_not_citable`).
  Workers give their lesson text to the orchestrator.

- The user must put the lesson in a prompt or approve it before the agent can record it.
  The codes are `cite_not_user` and `refused_approval_needs_reply`. There is no fallback Markdown write.

- Library callers declare the cite role. The CLI checks it against the session. Muninn checks each quote against the transcript.
  A caller that controls the ref can give incorrect information without getting a refusal. The checks rely on the agent to follow the rules.

- For each add, the CLI uses `muninn session <caller session id>`. This also applies to quote-only adds.
  A ref from a different session gives `cite_not_own_session`. A quote-only quote must come from a user prompt in the caller's session or it gives `cite_not_user`.
  An approval must be a prompt of 80 chars or fewer directly after the reply. If it does not satisfy this condition, the code is `cite_bad_approval`.
  The library default for `Record.cite_role/cite_kind` is empty (`cite_not_user`). A programmatic caller must declare the anchor.

  The check can accept text from an agent if the transcript records it as a user prompt in the caller's session. This includes hook or tool output.
  It can also accept a short approval that follows a reply but refers to different content. The check does not connect the claim to the reply text.

- The agent can bypass the adapter by calling `muninn know add|retract` directly. Readers check for a nonempty cite and quote but do not check the anchor.
  An agent can set `memory.backend: off` in the workflow config. This produces `memory_backend_off` and a diagnostic log entry.
  There is no gate for the switch. There is no Bash-gate denial for direct Muninn writes. These controls rely on the agent to follow the rules.

- `--supersedes` and `--contradicts` must be `K<n>`. A different value gives `bad_record`.
  Muninn refuses a supersede across scopes (`refused_bad_supersedes`).
  In one scope, a record that quotes a user can retire a standing instruction.
  The `list_records` function keeps only entries in the given scope, which is global for `user`.

- `scripts/tests/muninn_contract_test.py` runs the same table of conditions against the actual `muninn` and the SQLite fake.
  It uses temporary `MUNINN_HOME`, `MUNINN_ROOTS`, and `HOME` values.
  It skips with a message only if `muninn` is not on PATH or does not have the Part A flags. It does not touch the live store.

## Handoff notes

- In the Muninn repository, `muninn session` prints `preview`, which can show only part of the text.
  A text field in `--json` could let callers quote the reply in full.
  A new machine has no store until `muninn ingest`.
  On a missing store, `know list` exits 4 with `store_unavailable`. The adapter reports `muninn_store_missing`.
