# Dispatch contract measurement

[Measurement of provider parity](graph-alignment-measurement.md).

This document describes the source contract in the candidate plugin. It does not show that an installed hook ran.

| Verification | Status |
|---|---|
| Source | The two providers use the same graph contract and source check modules. |
| Local | Contract and dispatch tests check operations that the hook accepts or refuses. |
| Installed | Run allowed and refused dispatch checks in a new Claude session and a new Codex session. |
| Operation | To use the log counts, name the session and get its native records. |

## Structured dispatch envelope and role assertion (measurement note)

`begin-wave` saves one record in `graph.dispatches[dispatch_id]`.
The record identifies the node, wave, revision, and try. It records one authorization use and a digest of the rendered prompt sections.

The closed contract sets the role, model role, base ref, source checkout, source manifest and hashes, and publication command.
It also sets the lesson digest, write scope, phase selection, and mandatory context.
The field sequence is in `graph_contract_render.py`. One machine field records if the worker keeps or removes previous code.

The shared contract checks the prompt, record, role, and mandatory skills and checks.
The two providers use copies of the shared code. Before a worker starts, a source-bound item also checks its assigned Git checkout and current commit.
The checkout must be clean for tracked and usual untracked files. The check skips files that Git ignores.

Version 3 of `state_minor` sets `context_from_revision`.
At or after that revision, a new dispatch must include the context from the registered node and item facts.
The reader can read prompt hashes saved before the cutoff.

Conversion refuses an open wave or a damaged dispatch record from before conversion.
The Claude and Codex guards check new dispatches. Checks at the end of the loop read the saved native record again.

Authorization writes `authorize-dispatch/refused/<code>` or `authorize-dispatch/authorized/dispatch_authorized` to `recovery-trace.jsonl`.
The script `scripts/lib/dispatch_counters.py` counts these entries. Its `--trace-json` option also reads a graph measurement from standard input.
The reader refuses JSON `null`. It counts log entries, so one worker can have more than one count.

Flip condition:

- `role_mismatch` above zero means the prompt names the incorrect agent type, for example a scout dispatched as `general-purpose`.
- `dispatch_replayed` above zero means a spawn ran again or someone used the prompt again.
- `dispatch_sections_missing` means the orchestrator did not copy `prompt_sections` verbatim.
- Compare `dispatch_authorized` with the loop's wave count to check that the hook sees each spawn.

Negative controls in `packages/tests/test_provider_dispatch_envelope.py` each make one test fail.
Check only the first line, skip the step that calculates the digest, or drop the replay record. Two more controls remove the role assertion or put `TASK_NAME` back in the Codex hook.

The sandboxed Bash launcher carries no agent type, so it does not check the role.
The check cannot verify PreToolUse `tool_use_id`, so it uses a consumed flag to limit authorization to one use.
A guarded scout can run only if the plugin agent is installed.
Codex role containment is out of scope. The contract checks only `agent_type == role`.

The session user can edit the stored record. The check finds unintended changes but cannot prove that no one edited the file.
The first-line reader for `CollabAgentToolCall` in `graph_transcript` reads historical transcripts.
For calls that use the contract, Codex checks the native function-call message, record, role, and consumed authorization at `record-wave` and at loop end.

The off switch `CODERAILS_GRAPH_DISPATCH=off|0|false` skips the contract, hash, role, and consumption policy. By default, the dispatch checks are ON.
The check continues to look for a current v2 ownership envelope and native records for the node, wave, and try.
The counter `dispatch_check_off` counts uses of the switch.

For Claude, the native Agent call must have the same tool ID as the non-null ID in the hook.
The check looks again at the role, consumption, and single spawn for that ID.
See the RUNBOOK for limits on prompt body, `write_scope`, unguarded roles, `SendMessage` or resume, and missing hook tool IDs.

Current native Codex calls give the hook an encrypted prompt. The hook records `dispatch_prompt_unverifiable`.
It refuses the spawn without consuming its dispatch record. These checks do not show that a native Codex graph worker ran.
Run graph work through the checked local Codex OAuth driver after you install it.

**Reproduce.**

```
python3 scripts/lib/dispatch_counters.py
python3 hooks/scripts/tests/graph_contract_test.py && python3 hooks/scripts/tests/graph_dispatch_guard_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_dispatch_envelope packages.tests.test_codex_dispatch_guard
```
