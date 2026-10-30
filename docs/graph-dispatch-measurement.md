# Dispatch contract measurement

[Graph alignment measurement](graph-alignment-measurement.md).

This note describes the source contract in the candidate plugin. It does not show that an installed hook ran.

| Evidence | Status |
|---|---|
| Source | Both providers use the same graph contract and source check modules. |
| Local | Focused contract and dispatch tests exercise allowed and refused requests. |
| Installed | A new Claude session and a new Codex session still need allowed and refused dispatch checks. |
| Operation | Trace counts need a named session and its native records before they can describe use. |

## Structured dispatch envelope and role assertion (measurement note)

`begin-wave` saves one record in `graph.dispatches[dispatch_id]`. The record binds the node, wave, revision, attempt,
one authorization use, and a digest of the rendered prompt sections. Its closed contract binds the role, model role,
base reference, source checkout, source manifest and hashes, publication command, lesson digest, write scope, phase
choices, and required context. `graph_contract_render.py` defines the exact field order. One machine field records
whether old code is kept or removed.

The shared contract code checks the prompt, record, role and required skills and checks. Both providers use copies of
the shared code. A source-bound item also checks its assigned Git checkout and current commit before a worker starts.
The checkout must be clean for tracked and ordinary untracked files. Git-ignored files are outside this check.

Graph state minor 3 sets `context_from_revision`. A new dispatch at or after that revision must bind required context
from the registered node and item facts. Older saved prompt hashes remain readable before the cutoff. Conversion
refuses an open wave or damaged old dispatch record. The Claude and Codex guards check new requests. Completion checks
the saved native record again.

Authorization writes `authorize-dispatch/refused/<code>` or `authorize-dispatch/authorized/dispatch_authorized` to
`recovery-trace.jsonl`. `scripts/lib/dispatch_counters.py` counts these rows. Its `--trace-json` option also reads a
graph measurement from standard input. JSON `null` is refused. These are event counts, not unique worker counts.
Flip condition:
`role_mismatch` above zero means a prompt names the wrong agent type (a scout dispatched as `general-purpose`);
`dispatch_replayed` above zero means a spawn was retried or a prompt was reused; `dispatch_sections_missing` means
orchestrators are not pasting `prompt_sections` verbatim; `dispatch_authorized` against the loop's wave count shows the
guard sees every spawn. Negative controls (each fails its row of `packages/tests/test_provider_dispatch_envelope.py`):
compare only the first line, skip the digest recompute, drop the replay record, delete the role assertion, restore
`TASK_NAME` in the Codex hook. Limits: the sandboxed Bash launcher carries no agent type (role not asserted there); the
PreToolUse `tool_use_id` is unverified, so single use falls back to a consumed flag; a plugin agent that is not installed
cannot run a guarded scout; Codex role containment is out of scope (`agent_type == role` only); the stored record is a
plain same-user file (drift detection, not tamper evidence); `graph_transcript`'s `CollabAgentToolCall` first-line reader is
a historical-transcript path; contract-era Codex binding now also rechecks the native function-call message, record,
role and consumed authorization at `record-wave` and completion. Off-switch `CODERAILS_GRAPH_DISPATCH=off|0|false`
(default ON) bypasses contract/hash/role/consumption policy but still requires a current v2 ownership envelope and
native node/wave/attempt evidence; `dispatch_check_off` counts its use. Claude evidence matches a non-null hook tool id
to the native Agent call and re-asserts role, consumption and one spawn per id. Prompt body, `write_scope`, unguarded
roles, `SendMessage`/resume and absent hook tool ids remain the RUNBOOK limits.

Current native Codex calls give the hook an encrypted prompt. The hook records `dispatch_prompt_unverifiable` and refuses
the spawn without consuming its dispatch record. These checks do not establish a successful native Codex graph worker.
Run graph work through the checked local Codex OAuth driver after it is installed.

**Reproduce.**

```
python3 scripts/lib/dispatch_counters.py
python3 hooks/scripts/tests/graph_contract_test.py && python3 hooks/scripts/tests/graph_dispatch_guard_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_dispatch_envelope packages.tests.test_codex_dispatch_guard
```
