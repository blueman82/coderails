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

## Authority object refused or changed

- Symptom: `authority.py` refuses a command, or an object disappeared.
- Query: `trace.by_reason` for `authority/created|narrowed|revoked` and `authority/refused/authority_refused_<cause>`, cause one of `exists`,
  `widen_scope`, `widen_max_prs`, `narrow_empty`, `not_revocable`, `missing`, `expired`, `malformed`, `invalid`,
  `create_invalid`, `write_failed`, `foreign` (an unsafe session id cannot be traced; stderr only).
- Remediation: inspect with `python3 scripts/authority.py inspect --session <exact id>`. A foreign-session refusal
  means the id did not match exactly; ids are never sanitised.

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
