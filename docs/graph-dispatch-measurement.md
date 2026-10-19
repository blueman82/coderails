# Dispatch envelope measurement note

[Graph alignment measurement](graph-alignment-measurement.md).

## Structured dispatch envelope and role assertion (measurement note)

The first-line-only five-field envelope (Claude) and the `TASK_NAME` regex plus `CODERAILS_GRAPH_TASK` marker (Codex, which
let any spawn through whose task name and agent type looked non-graph) are replaced by one record. `begin-wave` stores
`graph.dispatches[dispatch_id]` (node, wave, revision, attempt, the closed contract `role, model_role, base_ref, manifest,
disposition, lessons, write_scope, skip_phases, scope`, its sections digest, a single-use `authorized` slot) and prints the
first-line v2 envelope plus the rendered sections to paste. The shared `packages/graph-semantics/graph_contract.py`
(materialized byte-for-byte into both script dirs by `scripts/installer/files.py`) validates the contract, renders it
deterministically, cross-checks a prompt against the stored record and asserts the role against `capabilities/profiles.json`.
Claude's `Agent` guard and Codex's `spawn_agent` guard (now enforcing for every spawn of a graph-bound session) both call it
through `authorize_dispatch` / `graph.py authorize-dispatch`; Claude's completion revalidation re-checks each bound spawn's
record and digest for waves at or after `graph.contract_from_revision`. `graph.py convert` takes `state_minor` 1 to 2 and
refuses while a wave is open. Rows go to `recovery-trace.jsonl` as `authorize-dispatch/refused/<code>` and
`authorize-dispatch/authorized/dispatch_authorized`; `python3 scripts/lib/dispatch_counters.py` tallies them (own module
because `scripts/measure_graph_alignment.py` is at its line limit; folding it in is handoff H1). Flip condition:
`role_mismatch` above zero means a prompt names the wrong agent type (a scout dispatched as `general-purpose`);
`dispatch_replayed` above zero means a spawn was retried or a prompt was reused; `dispatch_sections_missing` means
orchestrators are not pasting `prompt_sections` verbatim; `dispatch_authorized` against the loop's wave count shows the
guard sees every spawn. Negative controls (each fails its row of `packages/tests/test_provider_dispatch_envelope.py`):
compare only the first line, skip the digest recompute, drop the replay record, delete the role assertion, restore
`TASK_NAME` in the Codex hook. Limits: the sandboxed Bash launcher carries no agent type (role not asserted there); the
PreToolUse `tool_use_id` is unverified, so single use falls back to a consumed flag; a plugin agent that is not installed
cannot run a guarded scout; Codex role containment is out of scope (`agent_type == role` only); the stored record is a
plain same-user file (drift detection, not tamper evidence); `graph_transcript`'s `CollabAgentToolCall` first-line reader is
a historical-transcript path, live Codex binding stays on `task_name`. Off-switch `CODERAILS_GRAPH_DISPATCH=off|0|false`
(default ON) bypasses the guards, counted as `dispatch_check_off` (high = workaround). Claude evidence re-asserts role,
consumption, one spawn per id; Codex has none; prompt body, `write_scope`, non-scouts, `SendMessage`/resume: RUNBOOK limits.

**Reproduce.**

```
python3 scripts/lib/dispatch_counters.py
python3 hooks/scripts/tests/graph_contract_test.py && python3 hooks/scripts/tests/graph_dispatch_guard_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_dispatch_envelope packages.tests.test_codex_dispatch_guard
```
