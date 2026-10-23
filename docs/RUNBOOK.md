# Runbook: hook and trace observability

Trace rows are NON-AUTHORITATIVE: fail-open, append-only, one `event_id` per event, written by
`hooks/scripts/lib/trace_row.py` to `<agentic-loop dir>/<session_id>/trace.jsonl` (the same per-session directory
`crack_on_gate.py` uses, with or without a loop). Rows hold `schema_version`, `event_id`, `session_id`, `loop_id`
(null outside a loop), `ts`, `command`, `outcome`, `reason_code` and sha256-hashed `inputs`. No gate decision
reads them. Counters dedupe by `event_id`, skip torn lines, and key tallies as `command/outcome/reason_code`.

Query every entry below with:

```
python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['trace'])"
```

## No trace rows appear

- Symptom: `trace.rows` is 0 although gates fired (`gate_blocks` counts are nonzero).
- Query: the command above; then `ls ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
- Remediation: the writer fails open, so an unwritable directory or an unsafe session id (contains `/` or `..`,
  or is empty) silently drops rows. Fix the directory permissions; do not make the gate depend on the write.

## Gate seems off (config key or wiki schema)

- Symptom: a configured gate (wiki taxonomy, wiki-debt, integrity, eval signing) does nothing, or a config key seems ignored.
- Query: `python3 scripts/lib/config.py resolve-config --json | jq .unknown_keys` (also `.findings`); counts via
  `python3 scripts/lib/config_counters.py` for `config_unknown_key`, `config_bad_type`, `config_unreadable`,
  `wiki_schema_missing`, `wiki_schema_invalid`, `wiki_schema_legacy` (scope with `--since 2026-10-05T00:00:00`; the same rows
  also appear in `measure_graph_alignment.py --json` under `trace.by_reason`; trace rows: `config/warned/<code>`, `wiki_taxonomy_gate/failed_open/<code>`).
- Remediation: fix the key (the finding carries a did-you-mean hint) or the value type; for `wiki_schema_*` restore or
  repair `wiki.schema.json` (`page_types` non-empty list of directory names). Both are fail-open by design: findings never
  change a gate's decision, and a stale AGENTS.md Page types table fails the build (`config_docs_drift_test.py`), not the hook. `wiki_schema_legacy` means a vault still has only
  `AGENTS-wiki-schema.md`: policing continues from its Page types table; add `wiki.schema.json` to retire the fallback.

## Discipline lint advisories climbing

- Symptom: `confidence_labels` or `verify_loop` advisories climb. These two hooks no longer block (demoted by user
  override, `docs/decisions/2026-10-04-not-in-gate-demotion.md`); the pre-demotion `blocked` series is history.
- Query: `trace.by_reason` for `check_confidence_labels/demoted/confidence_label_missing` and
  `check_verify_loop/demoted/verify_loop_missing` (keys are `command/outcome/reason_code`; `blocked` and `warned`
  rows are the older series and are separate); `gate_blocks.claude.gates.<gate>` for `demoted`/`would_block`.
  `blocked / decisions` now falls to about 0 by construction; compare `demoted / decisions` instead.
- Remediation: a rising `demoted` count means the model is skipping labels or DNV tags, not that a gate is stuck.
  Fix the prompt or instruction text; there is nothing to unblock.

## Reviewer/scout Bash command denied

- Symptom: a read-only reviewer or scout reports a denied Bash call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/bash_allowlist_deny_<cause>`, cause one of `meta`
  (chaining/redirection), `flag` (dangerous or unknown rg flag), `parse` (bad quoting), `argv` (command not on the list).
  The discipline log line carries `agent_type`, `argv0` and a 12-char sha of the command.
- Remediation: rerun the inspection with a single allowlisted read-only command (no chaining, redirection or
  interpreters). If a legitimate command is missing, add its exact argv prefix to the allowlist with a test.

## Capability tool refused or denied

- Symptom: a reviewer/scout (usually `source-auditor` running `tests.run`) is refused a `scripts/capability.py` call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/capability_denied_<tool>`,
  `capability_unknown_tool` or `capability_bad_argv` (hook side, one row per decision;
  `reviewer_bash_allowlist/allowed/capability_allowed_<tool>` counts grants), and `capability/refused/capability_*`
  (script side: `args_invalid`, `path_denied`, `bad_ref`, `no_repo`, `tests_unknown_name`, `sandbox_unavailable`, `io_error`). Narrow with
  `python3 scripts/measure_graph_alignment.py --root . --json | jq '.trace.by_reason | with_entries(select(.key|test("capability")))'`.
  Hook rows need a session id (payload `session_id`); script rows use env `CLAUDE_SESSION_ID` or `CODEX_THREAD_ID`
  (unverified that the harness sets it) and otherwise land under the `unattributed` session directory. `"traced": false`
  now means only that the trace library or disk failed; the hook also logs `denied=1 reason_code=...` to its log, so an empty query is not proof
  of no refusals.
- Remediation: `capability_denied_*` means the agent's profile lacks the tool; change `capabilities/profiles.json`
  deliberately (the validator test keeps frontmatter and Codex sandboxes in step), never widen Bash. `bad_argv` means
  the call was not exactly `<abs path>/scripts/capability.py <tool> --json-args '<json>'`; the path must be absolute.
  `tests_unknown_name` means the name is not in `profiles.json` `tests`.

## Authority object refused or changed

- Symptom: `authority.py` refuses a command, or an object disappeared.
- Query: `trace.by_reason` for `authority/created|narrowed|revoked` and `authority/refused/authority_refused_<cause>`, cause one of `exists`,
  `widen_scope`, `widen_max_prs`, `narrow_empty`, `not_revocable`, `missing`, `expired`, `malformed`, `invalid`,
  `create_invalid`, `write_failed`, `foreign` (an unsafe session id cannot be traced; stderr only).
- Remediation: inspect with `python3 scripts/authority.py inspect --session <exact id>`. A foreign-session refusal
  means the id did not match exactly; ids are never sanitised.

## Manifest says no loop, or the wrong loop

- Symptom: the SessionStart manifest shows `loop: none` or `loop: unknown` although a loop is running, or the
  session injected the static fallback.
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['context'])"`,
  or `jq 'select(.command|startswith("context_"))|.reason_code' ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
  Reason codes: `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`,
  `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`, `route_none`
  (an unrouted prompt: no row is written). Events with a missing or unsafe session id are filed under
  `<loop dir>/_unattributed/trace.jsonl`.
- Remediation: `loop: none` for a foreign or unsafe session id is correct (ids match exactly, never sanitised). For
  `manifest_state_unreadable` repair progress.json; for `manifest_graph_invalid` run `graph.py inspect <state>`.
  Check `CLAUDE_AGENTIC_LOOP_DIR` (wins) versus `CODERAILS_AGENTIC_LOOP_DIR`. Routes are advisory text only.

## Crack-on denial wrong (stuck on, or off too early)

- Symptom: `AskUserQuestion` / `request_user_input` is denied when the user no longer wants autonomy, or is allowed
  right after "crack on".
- Query: `trace.by_reason` for `crack_on/granted/authority_granted`, `crack_on/blocked/authority_deny`,
  `crack_on/allowed/authority_expired_allow`, `crack_on/blocked/crack_on_legacy_flag`,
  `crack_on/ignored/authority_corrupt_ignored` (authority.json unparseable: treated as none; legacy flag still honoured),
  `crack_on/failed_open/authority_write_failed` (user said "crack on" but no authority was written, so nothing is
  suppressed; if the trace dir is also unwritable only the `stamped=0 err=write_failed` discipline.log line remains),
  `authority/refused/authority_refused_foreign`. Inspect with
  `python3 scripts/authority.py inspect --session <exact id>`.
- Remediation: revoke with `python3 scripts/authority.py revoke --session <id>` (also deletes any legacy flag). An old flag
  (`crack_on_legacy_flag`) is cleared with `rm <loop dir>/<id>/crack_on_active` (Codex:
  `$PLUGIN_DATA/sessions/<id>/crack_on_active`). Allowed right after "crack on": the phrase was quoted, backticked,
  negated or asked as a question (by design), or `authority_expired_allow` shows the 24h object lapsed; say "crack on" again to re-grant.
- Baseline note: the old 103 fires / 5 blocks figure (`docs/graph-alignment-measurement.md`) came from discipline-log
  telemetry; after-numbers come from trace rows, so they are not comparable. Reproduce:
  `python3 scripts/measure_graph_alignment.py --root . --json`.

## Memory degraded (Muninn authoritative)

- Symptom: a typed lesson, decision or handoff read/write printed `{"degraded": "<reason_code>"}` and exited 3.
  Muninn is the only typed-memory store. There is NO Markdown fallback: a degrade is reported with its reason code,
  never skipped and never replaced by hand-written Markdown. `memory.backend: off` is the one explicit way to run
  without it (reason `memory_backend_off`, traced).
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`
  (`rows`, `by_reason_code`, `by_command`; deduped by `event_id`; commands `memory.*`, `decision.*`, `order.*`,
  `lesson.*`, `proof.*`, `retro.*`, `teardown.*`, `handoff.*`), or
  `grep '"command": "memory\.' <agentic-loop dir>/<session_id>/trace.jsonl`. An unsafe session id writes no row; an unset
  or empty session id (CLI without `CLAUDE_SESSION_ID` or `--session`) writes rows under the fixed id
  `memory-adapter-nosession`. A muninn refusal keeps its original code in the reason (`refused_<code>`).
- Remediation (reason code: one-line fix, single source `scripts/lib/memory_reasons.py`):

| Code | Remediation |
|------|-------------|
| `memory_backend_off` | memory.backend is off in the workflow config; set it to muninn (or remove the key) to write typed memory. |
| `memory_backend_invalid` | memory.backend must be muninn or off; fix the value in .coderails/workflow.config.yaml. |
| `muninn_absent` | muninn is not on PATH; install it (the Markdown path is not a fallback). |
| `muninn_old_ledger` | muninn lacks the Part A flags (--scope-loop, --confidence, ...); upgrade muninn. |
| `muninn_timeout` | muninn hung past 10s; run `muninn know list` by hand and check store locks. |
| `muninn_error` | muninn exited nonzero or returned unparseable JSON; rerun the same `muninn know ...` command and read stderr. |
| `muninn_bad_output` | muninn wrote the entry but printed no K-id; run `muninn know list --scope-loop <id>` to find it. |
| `muninn_store_missing` | no Muninn store at $MUNINN_HOME (or ~/.local/share/muninn); run `muninn ingest` once. |
| `muninn_schema_old` | the store is schema v1 (PRAGMA user_version != 2); upgrade it with muninn itself, never by hand. |
| `muninn_schema_incomplete` | the store lacks a typed column or table (confidence, valid_until, sensitivity, contradicts, tags, fts); run `muninn doctor`. |
| `uncited_write` | give a verbatim --quote (and --cite ref); a record without a quote is never written. |
| `restricted_refused` | restricted records are never written by the adapter; write a normal-sensitivity claim. |
| `bad_record` | the record failed validation (type, scope, tag, date, empty claim, or loop scope without a loop id). |
| `handwritten_protected` | the render target is hand-written (no generator marker); render to a new path. |
| `cite_not_user` | the cite must anchor in a user prompt; cite the owner's own words or use the approved-reply form. |
| `cite_too_short` | a quote-only cite needs 12 to 300 characters; quote more of the user's prompt or cite an approval with its reply. |
| `cite_unresolved` | the cite ref (or the quote, for a quote-only cite) was not found in `muninn session <root>`, or the approval has no reply before it, or no session id was given; check the ref. |
| `cite_not_own_session` | the cite ref belongs to another session; only a prompt of the caller's own session (--session) can anchor a write. |
| `cite_bad_approval` | the approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers. |
| `refused_uncited` | muninn got no citation; pass --cite/--quote. |
| `refused_not_found` | the cite ref does not resolve; run `muninn ingest` and check the ref. |
| `refused_not_citable` | the cited event is a subagent thread; only the orchestrator session can write typed records. |
| `refused_quote_length` | the quote must be 12 to 300 characters (a shorter one is valid only as a whole approval prompt). |
| `refused_quote_not_found` | the quote is not verbatim in the cited event; copy it exactly. |
| `refused_approval_needs_reply` | a short approval needs the reply it answers cited too; use the approved-reply form (--approval REF). |
| `refused_preference_needs_user` | a preference must cite a user prompt. |
| `refused_bad_supersedes` | the superseded K-id is missing, not current, or in another scope. |
| `refused_bad_contradicts` | the contradicted K-id does not exist. |
| `refused_bad_valid_until` | valid_until must be a future ISO date. |
| `refused_bad_tags` | tags must match [a-z0-9_-]{1,32}. |
| `refused_bad_loop_scope` | the loop id is invalid, or --global was combined with a loop scope. |
| `refused_bad_kind` | the record kind is not one muninn accepts. |
| `refused_text_length` | the claim must be 1 to 500 characters. |
| `refused_no_caller_session` | quote-only writes need CLAUDE_CODE_SESSION_ID or CODEX_SESSION_ID in the environment. |
| `refused_other` | muninn refused with a code not listed here; the reason is `refused_<code>`, read it and the muninn docs. |
| `decision_wrong_session` | the loop state belongs to another session; record only from the owning session. |
| `decision_blank_phase` | a decision needs a non-blank phase (for example 2.5). |
| `decision_blank_decision` | a decision needs a non-blank decision text; nothing was written. |
| `decision_invalid_chain` | the decision chain is damaged; inspect and preserve the loop state before any further sync. |
| `decision_sync_unknown` | a decision sync may have reached Muninn; inspect the store before any manual retry. |
| `decision_state_error` | the loop state could not be read, validated or locked; nothing was written. |
| `order_chain_broken` | orders.json was edited by hand (the hash chain names the order); restore it from backup or review the named order, then re-seal by recording through orders.py. |
| `order_blank_field` | an order needs a non-blank failure mode and lesson; nothing was written. |
| `order_lesson_too_long` | the collapsed lesson exceeds 500 characters; provide a shorter complete claim, never truncate it. |
| `order_bad_id` | an explicit order id must match [a-z0-9][a-z0-9_-]{0,119}; use a canonical id. |
| `order_id_collision` | that id names another failure mode or scope; use its real identity or a distinct id. |
| `order_not_found` | no order with that id in orders.json; check the id with `orders.py lessons`. |
| `order_state_error` | orders, preparation or receipt could not be read, locked or written; check the repo-key dir, orders.lock and persistent teardown.jsonl.lock. |
| `order_loop_unknown` | no source at <repo-key dir>/<session>/progress.json; pass its owning --session and separate logical --loop. |
| `order_wrong_session` | the source directory, session or logical loop is foreign; use the owning directory and identifiers. |
| `order_source_invalid` | progress, preparation or observations are malformed; restore genuine validated source artifacts. |
| `order_source_mismatch` | the prepared source/hash is stale; before completion use `prepare --refresh-from-sha256` with its CURRENT `evidence_sha256`. |
| `order_loop_ineligible` | graph or work units are incomplete or stopped; finish the existing completion requirements. |
| `order_not_complete` | preparation is prospective; durably save owned progress complete before recurrence or aging. |
| `order_pending_teardown` | completion saved but local apply or observation failed; retry tick with the same bound source. |
| `order_retro_validator_unavailable` | schema3 retros need the matching retro_check.py validator; reconcile that source dependency before graduation. |
| `order_already_ticked` | this session and logical loop were already counted; the tick was skipped (informational). |
| `no_user_cite` | the order was stored without a user quote; attach it with `orders.py cite <id> --quote <verbatim owner prompt text>`. |
| `legacy_uncited` | an imported hand-written order has no cite yet; attach one with `orders.py cite <id> --quote`. |
| `legacy_parse_error` | the local legacy input has an incomplete, ambiguous or colliding entry; fix it while preserving the original. |
| `legacy_missing` | there is no hand-written standing-orders.md to import (absent, empty or already generated). |
| `lesson_not_current` | no unambiguous current cited claim exists; inspect conflicting current evidence, or explicitly re-record a retracted/expired lesson with a fresh quote. |
| `retro_not_assembled` | Assemble schema-3 retro.json with `retro.py assemble`; preserve the source artifacts. |
| `retro_source_mismatch` | A named source changed after assembly; finish that source and re-assemble. |
| `retro_decisions_chain_broken` | Restore the damaged decision row; record decisions through the graph CLI. |
| `retro_steps_missing` | Run the missing proof, decision flush or orders preparation step, then re-assemble. |
| `retro_state_error` | Restore the owned, readable progress.json before assembly. |
| `retro_wrong_session` | Use the session that owns progress.json. |
| `retro_free_invalid` | Supply one JSON object in the free-file. |
| `handoff_state_unreadable` | Pass the readable, owned progress.json to handoff_derive. |
| `graph_unavailable` | Run graph.py summarize and inspect to diagnose the unavailable graph. |

- Limits: only the orchestrator session can write (subagent threads are not citable); cites must anchor in a user
  prompt; the hash-chained ledgers are a cooperating-agent safeguard, not a security boundary. Measurement note: compare
  `by_reason_code` before and after a change; a rising `muninn_absent` or `refused_approval_needs_reply` is the signal.
  See `docs/decisions/2026-10-05-memory-authoritative.md`.

## Decision recorded locally but Muninn sync degraded

- Symptom: `graph.py record-decision` printed `"exit_code": 3` and a `muninn.reason_code`. The decision was appended
  to `progress.json` `decisions_absorbed` before the sync attempt. For `unknown` or `syncing`, the Muninn copy may
  already exist; inspect both stores before any recovery. A loop restarted during sync may no longer contain that row.
  Trace rows: `decision.record/recorded/ok`, then `decision.sync/<written|degraded|disabled>/<reason_code>`.
- Query: `python3 -c "import json;[print(r['seq'],r['muninn']) for r in json.load(open('progress.json'))['decisions_absorbed']]"`,
  or `grep '"command": "decision\.' <agentic-loop dir>/<session_id>/trace.jsonl`. Chain check:
  `python3 -c "import json,sys;sys.path.insert(0,'.');from scripts.lib import decision_record as d;print(d.verify_chain(json.load(open('progress.json'))['decisions_absorbed']))"`.
- Fix: read the reason in the table above. An authorising prompt of "yes" (`cite_too_short`) is expected to degrade: at
  teardown run `flush_pending(path, session, transition=..., cite_quote="<a substantive sentence the owner typed>")`;
  the same `seq` is patched to `written`. Rows are never deleted or rewritten to clear a degrade.
- Limits: the chain is a cooperating-agent safeguard (a same-user agent can rewrite file and chain), and dropping the
  last row is detected only by the in-file head anchor, which the same agent can also rewrite. Measurement note: `docs/typed-records-measurement.md`.

## Standing order stored without a cite, or a lesson missing from dispatch

- Symptom: `orders.py record` exited 3 with `muninn.reason_code` (`no_user_cite`, `muninn_absent`, `cite_*`), or
  `lessons.py query` / `orders.py lessons` exited 3 with `{"degraded": ...}`, or an order you recorded is absent from the
  list. Before completion, `record` stages bound inputs and syncs the cited claim without lifecycle effects. After
  owned progress is durably complete, local apply records recurrence and aging in `orders.json`. A degraded store
  result retains any prior K-id. `lessons` never prints ledger text when Muninn is down (`memory.backend: off` is the
  explicit switch). Trace rows: `order.record|prepare|tick|render|import|cite`, `lesson.query|predicate`.
- Query: `python3 scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract`
  reads current cited lessons. Diagnostic `orders.py ... lessons` also returns an `excluded` list naming entries
  is retracted, expired or superseded, reason `lesson_not_current`), or
  `grep -E '"command": "(order|lesson)\.' <agentic-loop dir>/<session_id>/trace.jsonl`. A hand edit of `orders.json` is
  refused with `order_chain_broken` naming the order.
- Fix: read the reason in the table above. For `no_user_cite` / `legacy_uncited` run
  `orders.py --dir <repo-key dir> cite <id> --quote "<verbatim words the owner typed>"` from the owning session. To
  adopt the old hand-written file run `orders.py import-legacy` once (it moves the original to
  `standing-orders.legacy.md`, never deletes it), then `orders.py render`.
  This importer is for one-time cutover only; retire it after conversion and use typed orders thereafter.
- Apply contract: use `--dir <repo-key dir> --session <provider session>` with the separate logical `--loop` copied
  from `<repo-key dir>/<session>/progress.json`. Stage `record` inputs, then `prepare --loop <logical loop>` after
  the final progress-source mutations. Preparation validates ownership, revision, eligibility and hashes, and appends
  `orders_prepared`; it ages nothing. Run the existing native provider completion checks and durable save under the
  progress lock. After releasing that lock, run `tick --loop <logical loop>` and `render`. Tick holds only the orders
  lock and emits `orders_ticked` after its ledger save. A failed completion save ages nothing. A failed postcompletion
  ledger save or observation returns exit 3 and `pending_teardown: true`; retry the same tick to recover idempotently.
  Automatic provider completion wiring is pending in this source checkpoint; the instructed caller remains advisory.
- Completed text replacement: when this session/loop observation already exists, explicit `record` captures
  `replaces_source` in the prepared row. The canonical `lesson_source` hashes owned binding, authored fields and that
  predecessor, excluding mutable store observations, and is sealed/saved with the lesson. Ordinary tick recovers only
  the accepted row while preserving counters and evidence; an equal published token needs no replay. A later authored
  source is preserved. Without an exact validated success receipt for this preparation, a conflicting retry stays
  pending and emits no false completion receipt. Older absent predecessor fields are never retroactively invented;
  a captured null is distinct and cannot authorize delayed replacement without its own published source or exact
  validated acknowledgement, even if no later edit occurred. Direct completed explicit record remains available.
  Publication, receipt loss and then a later replacement can remain pending because these
  two retained facts do not prove historical application. Unbound pure-model record updates clear an old source token.
- Preparation recovery: changed sources are refused by default. Before completion, use
  `prepare --loop <logical loop> --refresh-from-sha256 <CURRENT evidence_sha256>` only with the canonical hash returned
  by the current preparation. Comparison happens under the same orders lock. Resolved directories, session and
  logical loop must match; revision cannot roll back, and no matching local tick or recurrence may already exist.
  Staged records are preserved, with no lifecycle effects. Wrong/stale hashes, invalid/foreign/complete sources and
  prior application refuse unchanged. A durably saved replacement with a failed preparation receipt leaves progress
  incomplete; ordinary unchanged `prepare` repairs the receipt without another replacement or duplicate observation.
  After durable completion, retry `tick` only. Flush and reload pending source updates before final prepare/refresh.
- Receipt publication: D4 refuses linked preparation, receipt and persistent sidecar paths before read/open/create.
  It holds orders.lock, then `teardown.jsonl.lock`, and validates every prior physical LF JSONL object, finite JSON
  number and terminal newline before deduplication, preserves prior bytes, and atomically publishes a complete
  fsynced sibling. Short writes make progress until complete; a zero write or partial-write exception leaves canonical
  evidence untouched. An ambiguous error after replacement needs an ordinary prepare/tick retry, without duplicate
  lifecycle effects. Pre-existing malformed or newline-less evidence is refused untouched; restore genuine evidence,
  never truncate or skip a tail. Other teardown publishers must adopt the same sidecar/framing/atomic publication
  contract to preserve concurrent events. D6 adoption remains pending; its latest-step dedupe policy is separate.
- Shared identity: an id binds failure mode and scope across the ledger and every valid retained preparation before
  record/cite sync or local application. Historical preparations still constrain identity after progress advances;
  they establish no present eligibility, currentness, citation or lifecycle effect. Same identities in other sessions
  are accepted recurrences; conflicts and foreign/malformed stored bindings refuse before superseding a store claim.
- Current citation: explicit `record` alone may replace lesson text. `cite` reconciles the current tagged claim even
  when the ledger holds older text, without a knowledge write. A formerly cited id without a current replacement
  refuses; a genuinely uncited first attachment still validates the owner's quote. Distinct simultaneous current
  claims refuse as `lesson_not_current`. Tick performs current reads without knowledge writes; outages retain saved
  K-ids over stale preparation metadata and return explicit degradation. Idempotent tick retry may refresh metadata
  without repeating lifecycle effects. Promotion uses the current cited join, independent of cached write state.
- Limits: the one same-user orders lock covers currentness, reconciliation, bounded sync and direct atomic ledger
  save; it provides no exactly-once network guarantee. Current tagged claims are reconciled even for degraded/pending
  local records. Only a new completed session+loop recurrence resets a counter or revives a tombstone; replaying the
  same observation cannot rejuvenate it. Authoritative dispatch, promotion and views use current, normal, live,
  verified user-cited claims. Diagnostic `orders.py lessons` may show uncited rows (`cited: false`); contract queries,
  promotion and views exclude them. Owner-cited lesson text is legitimate typed memory; advisory transcript
  observations remain metadata only. Failed reads exit 3, with no ledger-text fallback. A fresh cited claim can
  supersede prior text. Legacy import retains full source text and first-seen provenance, preserves decayed counters,
  and refuses duplicate/incomplete/colliding entries or an external source path without moving the original.
- Legacy retry: after a saved ledger and failed source move, ordinary `import-legacy` resumes only an entirely equal
  parsed cohort at one saved creation timestamp, excluding only seal fields from row comparison. It skips ledger save
  and moves intact source to an unused bounded backup slot. Mixed/new/divergent rows refuse. This proves parsed-row
  equivalence, not whole-source/preamble hash identity, own-attempt identity or a two-file atomic transaction.
- Graduation still requires >=10 distinct completed source-bound retros, recurrence and decay. Schema2 records need
  complete typed fields and their genuine completed progress hash. Schema3 delegates to `retro_check.check`; an absent
  validator returns `order_retro_validator_unavailable`, rather than a known zero count. Both ledger and source hashes
  remain a cooperating-agent safeguard: the same user can rewrite and recompute them.
  Measurement note: `docs/typed-records-measurement.md`; overlap decision:
  `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.
- Lesson attribution: pass the known native caller id with `--session`. The CLI also recognizes CLAUDE_SESSION_ID,
  CLAUDE_CODE_SESSION_ID, CODEX_THREAD_ID and CODEX_SESSION_ID, in that order; explicit input wins. Joined reads carry
  that id through query, predicate, diagnostic lessons and render to underlying degraded adapter traces. Environment
  support in source and private fixtures does not prove a variable is exported in an installed provider session.

## Stop declared in text instead of recorded, or a stop released unexpectedly

- Symptom: the Stop hook releases or blocks a loop and the model says it recorded nothing; or `progress.json`
  `loop_stop_counts` disagrees with the declared turn category. Stops are model-written intent rows
  (`progress.stops[]`, written by `graph.py stop`); `loop_stop_counts` stays the hook-owned count of consumed stops.
- Query: `python3 scripts/graph_alignment_stops.py --json` gives `stops_recorded`, `stops_consumed`,
  `legacy_text_parse` (the hook fell back to the final-line text, trace `loop_stall_guard/fallback/legacy_text_parse`)
  and `legacy_log_parse` (absent-state grace fell back to the discipline.log regex because `hook_state.json` was
  missing or torn). Inspect one loop with `python3 -c "import json;print(json.load(open('<progress.json>')).get('stops'))"`.
- Remediation: a high `legacy_text_parse` against `stops_consumed` means agents are not running `graph.py stop`: fix
  the prompt, and if it persists tighten the text parse rather than retiring it. An unconsumed row at the current
  revision releases the next Stop once, and only when `graph.py stop` ran after the last user prompt (an older row is
  ignored with trace `stale_stop_row`, so recording a stop early cannot excuse later undeclared turns); a row at an older revision is ignored by design. A refused `graph.py stop`
  prints the refusal on stderr (foreign session, unknown category or reason code, `complete` while the graph is
  unresolved); fix the argument, never edit `stops` by hand. Codex records the same row but only a `hard-stop` row on a
  typed hard-stopped graph releases its guard (`consume-stop`); other categories are recorded and ignored there.

## Proof gate blocked a `complete` declaration

- Symptom: `loop_stall_guard` (Claude) or `graph.py complete` / `verify-completion` (Codex) names frozen proofs as
  `P1(proof_...)`. The gate reads only `proof_results.jsonl` beside `proof.json`, written by the controller via
  `scripts/lib/proof.py`; the transcript and the `status` field are never consulted.
- Query: `python3 scripts/lib/proof.py status <state-dir>` (latest verdict per proof), or
  `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`
  (`by_reason_code` over `proof.freeze|run|gate` rows), or `grep '"command": "proof\.' <agentic-loop dir>/<session_id>/trace.jsonl`.
- Remediation (reason code: fix, single source `scripts/lib/proof_results.py` `REASONS`):
  `proof_unexecuted`: run `proof.py run <state-dir> --all`. `proof_failed`: the latest run exited nonzero or timed
  out; fix the cause, re-run. `proof_expect_mismatch`: exit code or stdout did not match the frozen `expect`.
  `proof_stale_cmd`: proof.json changed after the freeze row, or the run row hashes a different cmd; run
  `proof.py freeze` then `run`. `proof_stale_head`: the run belongs to another checkout or an earlier HEAD; run it
  again from the current repository checkout. `proof_chain_broken`: `proof_results.jsonl` was edited or lost rows; never hand-edit it,
  re-freeze and re-run (a fresh file). `proof_cmd_destructive`: the cmd matches the destructive classifier and was never
  executed; reword the proof. `proof_disposition_no_reason`: with no proof.json record `proof.py disposition <state-dir>
  --none --reason-code <code> --reason <text>`; a bare `none` or a code outside `DISPOSITION_CODES` (`docs_only`,
  `no_executable_surface`, `research_only`, `superseded`, `other`) is rejected, and a valid disposition is echoed in the
  gate output. `proof_no_proofs`: proof.json holds no non-withdrawn proof (an empty or withdrawn-only document); freeze a
  real proof or record a disposition. `proof_disposition_legacy` is a trace note
  only (string `none: <reason>` accepted). `proof_withdrawn_unobserved`: a withdrawn proof needs a failed/timeout run row
  and a reason.
- Limit: a same-user agent can forge rows and recompute the chain, as it could forge a transcript; this is a
  cooperating-agent safeguard, not a trust boundary. Also not covered: the destructive classifier is literal-pattern,
  not a sandbox, so obfuscated or interpreter-wrapped deletes (`python3 -c 'shutil.rmtree(...)'`, quote-split `rm`) still
  run; the latest freeze wins, so an agent can weaken a cmd or move a failing proof
  to `withdrawn_proofs` and re-freeze (only the frozen set is checked, not the loop's first one); schema 1 is refused at
  freeze; a disposition's reason is checked for presence and an enum code, not truth.
- Off-switch: none, by design. The proof gate is intentionally non-disableable on both providers (default ON, no config
  key or env var); the previous transcript-based check was removed, so there is no earlier behaviour to fall back to.

## Diff-manifest check warned or refused

- Symptom: `push.py` or `merge.py` prints `! diff_manifest <code>: <path>`, or refuses with `diff_manifest:<code>`
  (config `diff_manifest: enforce`). `scripts/diff_manifest.py --policy FILE` shows the same verdict without hooks.
- Query: `trace.by_reason` for `diff-manifest/ok/diff_manifest_ok`, `diff-manifest/warned|refused/<code>` (rows are keyed by
  `<repo>@<branch>` or `<repo>@pr-<N>`), plus `diff-manifest/failed_open/manifest_unreadable`,
  `diff-manifest/legacy/manifest_legacy_absent` (policy file without a manifest key; also written by the gate) and `diff-manifest/refused/foreign_session`. Tally them with
  `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/manifest_counters.py`.
- Codes: `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, `special_file_type` (type change, symlink or gitlink).
- Remediation: a real violation means the diff left its declared scope; fix the diff, or widen `unit.manifest`
  (re-register with `add-unit --manifest`) or the policy file on purpose. `manifest_unreadable` means the policy file,
  progress.json or diff could not be read (fails open when advisory; refuses under enforce); fix the path. Set
  `diff_manifest: off` to disable.

## Action-authority hook denied a merge or push (or warned in advisory)

- Symptom: `gh pr merge` or `git push` to main/master is denied with "needs an action receipt (<code>)" (enforce), or a
  stderr "action_authority (advisory)" warning appears. Only when config `action_authority` is `enforce` or `advisory`;
  absent or any other value is off.
- Query: `jq -r 'select(.command=="action_authority" or .command=="action_receipt") | [.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl`,
  or `trace.receipts.by_reason_code` from `python3 scripts/measure_graph_alignment.py --root . --json` (deduped by
  event_id). Codes: `denied_<code>` / `advisory_<code>` where `<code>` is one of `no_receipt`, `hash_mismatch`,
  `sha_mismatch`, `expired`, `revoked`, `consumed`, `foreign_session`, `foreign_loop`, `kind_mismatch`, `no_session` (payload had no session_id; traced under session dir `_no_session`), `malformed`;
  `receipt_consumed` (allowed); `action_authority_failed_open` (the hook itself errored and allowed);
  `receipt_approved` / `receipt_revoked` (CLI).
- `action_authority_failed_open`: the row carries `inputs.error_class` (sha256 of the exception class name; compare with
  `printf ZeroDivisionError | shasum -a 256`) and `loop_id` when known; the hook's stderr (hook log) prints
  `action_authority failed open: <Class>: <message>`. A session-less failure is traced under `_no_session`.
- Remediation: mint a receipt for the exact command:
  `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge|git_push --command '<exact command>' --cwd <directory it runs in>`
  (receipts are single-use, 1h by default; `inspect-receipt` / `revoke-receipt` take `--receipt-id`). `hash_mismatch`
  means args, cwd or branch differ from the minted command. `foreign_session` can also mean a worker whose
  `session_id` differs from the minter's (unverified guess): mint under the session the hook reports. Or set
  `action_authority: off` in `.coderails/workflow.config.yaml`.
- Scope of one receipt: each guarded segment of a chained command (`a && b`) needs its own receipt; a leading
  `cd <dir>` moves the directory the hash binds (mint with `--cwd` set to where the command really runs). A receipt
  minted with `--artifact-sha` verifies only against the real HEAD (push) or PR head via `gh pr view` (merge, 4s
  timeout; unknowable means `sha_mismatch`, fail closed).
- Codex: the hook is vendored and parity-tested, but `scripts/action_receipt_cli.py` is NOT shipped in the Codex
  package; mint receipts from a coderails repo checkout (same session id) or leave `action_authority` off.
- Limits: a receipt binds approval to an exact action but does not prove a human approved it (a same-user agent can run
  `approve-action`). The hash covers only the command text the hook sees, not aliases, functions, eval/xargs or scripts that
  push (env/sudo/subshell/`bash -c`/`gh api .../merge` wrappers are unwrapped). Limits: scope 500 chars, 8 KB per receipt,
  50 receipts per session (`receipt_refused_scope_too_long`, `receipt_refused_too_many`). Protected branches are main and master only.
