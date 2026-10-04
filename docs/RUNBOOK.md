# Runbook: hook and trace observability

Trace rows are NON-AUTHORITATIVE: fail-open, append-only, one `event_id` per event, written by
`hooks/scripts/lib/trace_row.py` to `<agentic-loop dir>/<session_id>/trace.jsonl` (the same per-session directory
`crack_on_gate.py` uses, with or without a loop). Rows hold `schema_version`, `event_id`, `session_id`, `loop_id`
(null outside a loop), `ts`, `command`, `outcome`, `reason_code` and sha256-hashed `inputs`. No gate decision
reads them. Counters dedupe by `event_id`, skip torn lines, and key tallies as `command/reason_code`.

Query every entry below with:

```
python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['trace'])"
```

## No trace rows appear

- Symptom: `trace.rows` is 0 although gates fired (`gate_blocks` counts are nonzero).
- Query: the command above; then `ls ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
- Remediation: the writer fails open, so an unwritable directory or an unsafe session id (contains `/` or `..`,
  or is empty) silently drops rows. Fix the directory permissions; do not make the gate depend on the write.

## Discipline gate blocking too often

- Symptom: `confidence_labels` or `verify_loop` blocks climb; users report repeated Stop blocks.
- Query: `trace.by_reason` for `check_confidence_labels/confidence_label_missing` and
  `check_verify_loop/verify_loop_missing`; `gate_blocks.claude.gates.<gate>` for blocked/decisions.
- Remediation: do not demote on volume alone. Apply rule (a) in `docs/graph-alignment-measurement.md` and the
  verdict in `docs/decisions/e1-confidence-gate-demotion.md` (a hand-sampled real-fix rate is required first).
