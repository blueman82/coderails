# Provider graph-alignment design

> Implementation update (2026-09-21). The approved design below is the specification before the cutover.
> The two-provider Python clean-break change in [the implementation plan](../plans/2026-09-03-provider-graph-alignment-implementation.md) replaces the shell paths and proposed `cmp` instructions below.

> Current installation uses `install.py` and `scripts/installer/files.py`. Current parity tests are in `packages/tests/test_provider_graph_parity.py`.
> The semantic source remains `packages/graph-semantics/graph_semantics.py`. Each provider bundle contains a byte-for-byte copy.
> This update does not change the frozen semantic contract.

## Problem and decision

The Claude graph contract comes from `skills/agentic-loop/loop-state.md` and `skills/agentic-loop/execution-graph.md`. Codex implements its contract in `packages/codex/skills/agentic-loop/scripts/graph.py`. (verified)
The two formats differ. The active-wave identifier is one difference. (verified)

**Decision.** One canonical Python core reads and changes new graph data. Claude and Codex use it through thin provider-local adapters.
The core only validates the graph and controls node readiness, changes to waves and retries, joins, and eligibility to complete. (verified)

This replaces the wiki's historical policy of one runtime for each provider for graph semantics only. (inferred)
Each provider continues to own scheduling, routing, transcript parsing, raw records, hooks, lock integration, and worker starts.
This keeps the safety property of that policy. (verified)

## Non-goals

- No shared scheduler, daemon, worker launcher, routing table, or provider selection policy. (verified)
- No shared transcript parser, collector or storage schema for verification records, or owner of raw records. (verified)
- No change to Claude `Agent` dispatch, records, locks, or hooks. (verified)
- No change to Codex `spawn_agent` dispatch, records, or hooks. (verified)
- No reconciliation between `work_units` and `graph.nodes`. Each has its own lifecycle and consumers. (verified)
- No migration, rewriting, or reinterpretation of historical graph files. (verified)
- No grandfathered semantic branch, legacy fallback, compatibility shim,
  dual-reader, dual-writer, automatic conversion, or mixed-version wave.
  (verified)

## Functional preservation and clean break

Keep all existing provider functions and safety properties during migration. They include validation, readiness, wave changes, joins, retry exhaustion, stale handling, and hard stops.
They also include locks, atomic writes, native dispatch, raw-evidence binding, and gates for evals, proofs, retrospectives, and loop end.
Green tests do not justify a refactor that silently removes one of these behaviors. (verified)

Use the aligned schema-v3 contract as the one implementation of this behavior. Keep no legacy compatibility path.

Before removing or replacing a semantic path, identify its consumers. Test its observable behavior with the frozen corpus or provider-local tests.
Remove the obsolete path in the same change. Keep historical v1/v2 graph files unchanged. The aligned runtime must reject them clearly. (verified)

## Canonical graph contract

### Scope and versioning

The canonical format is `schema_version: 3`. It applies only to new graph files after this change. (inferred)
Keep existing `schema_version: 1` and `2` files unchanged. The aligned runtime must reject them with a clear compatibility error.
There is no promise of compatibility with earlier readers. Do not migrate, dual-write, convert, or run mixed-version waves. (inferred)

The core receives the full `progress.json` document. It gives a full proposed document or a validation error.
It does not find files, get locks, read transcripts, or do I/O. (inferred)

### Root graph fields

`progress.json` keeps provider-owned root fields such as `session_id`, `loop_id`, `revision`, lifecycle `status`, `work_units`, and artifacts for loop end. (verified)
A new canonical root starts with `revision: 1`. (inferred) Its canonical `graph` value is:

```json
{
  "nodes": {},
  "edges": [],
  "joins": {},
  "active_wave": null,
  "hard_stop": null
}
```

`graph.nodes` uses only stable IDs from Claude. The authoritative grammar is:
`S-2|S-1|S0|S0.4|S0.5|S1|S2|S2.5|S2.6|J2|S2.7a|S2.7b|S2.7c|S2.7d[i]|S2.7e|S2.8|J2.8|U3[i]|U4[i]|U4b-review[i]|U5[i]|U5-repair[i]|U6[i]|U7/8[i]|U4b-merge-gate[i]|U10-respawn[i]|J12-all-units|G10|G11|G12|S9-wiki|S9-docs|S13-proof|S13-retro|S13-complete`.

Each `[i]` is a positive base-10 work-unit index. This includes `S2.7d[i]`.
`S*` steps run one time. `U<i>*` steps run for each work unit.
Use `J*` for IDs of joins. Use `G*` for IDs of checks that apply across the graph. (verified)

IDs are durable graph keys. Do not use them as display text. (inferred)

The authoritative display-label registry maps each label to its Claude source phase and step:

| ID template | Display label | Claude source phase and step |
| --- | --- | --- |
| `S-2` | `Initialize loop state` | `Stub state` |
| `S-1` | `Improve prompt` | `Improve prompt` |
| `S0` | `Read authorization envelope` | `Read envelope` |
| `S0.4` | `Record model cost` | `Model-cost notice` |
| `S0.5` | `Apply operating rules` | `Operating rules` |
| `S1` | `Plan work` | `Plan` |
| `S2` | `Run preflight` | `Plan` — pre-flight agent result, wiki/theme intake, retro lessons, and clean-base check |
| `S2.5` | `Resolve design fork` | `S2` design scout |
| `S2.6` | `Choose disposition` | `S2` scout for how to retire paths |
| `J2` | `Preflight decisions joined` | `S2.5` and `S2.6` joined |
| `S2.7a` | `Write specification` | durable `spec.md` |
| `S2.7b` | `Write implementation plan` | durable `plan.md` |
| `S2.7c` | `Freeze loop evals` | loop-scope evals frozen |
| `S2.7d[i]` | `Freeze unit i evaluation` | PR-scope evals frozen for unit `i` |
| `S2.7e` | `Freeze proof plan` | `proof.json` or decision that there is no executable surface |
| `S2.8` | `Assign model roles` | recorded model role for each build unit |
| `J2.8` | `Implementation ready` | first eligible unit inputs joined |
| `U3[i]` | `Build unit i` | worker produced unit `i` artifact/OPEN PR |
| `U4[i]` | `Verify unit i artifact` | orchestrator artifact check |
| `U4b-review[i]` | `Review unit i` | mandatory inspection and post-review artifact |
| `U5[i]` | `Diagnose unit i` | source-of-truth premise confirmed and diagnosis disconfirmed |
| `U5-repair[i]` | `Repair unit i` | different repair applied and checked |
| `U6[i]` | `Resolve continuation` | in-scope continuation decision resolved |
| `U7/8[i]` | `Push or deploy unit i` | stack-specific push/deploy tactic |
| `U4b-merge-gate[i]` | `Merge gate unit i` | inspection, eval, and integrity gate for the current head |
| `U10-respawn[i]` | `Respawn unit i` | new versioned worker and new worker start |
| `J12-all-units` | `All units joined` | each unit merge gate succeeded |
| `G10` | `Guard replacement worker` | replacement worker names versioned |
| `G11` | `Check confidence labels` | worker prompts and reports labelled |
| `G12` | `Fresh artifact check` | check the current artifact again at the boundary |
| `S9-wiki` | `Update wiki` | clustered wiki ingest and lint |
| `S9-docs` | `Sync docs` | `/sync-docs` audit and triage |
| `S13-proof` | `Run frozen proofs` | frozen proof commands ran and passed |
| `S13-retro` | `Write loop retrospective` | Phase 13 report and artifacts written |
| `S13-complete` | `Complete loop` | `Complete loop` |

Display labels are for human readers. The source-mapping column identifies the source step. The labels can use different words from the source titles. (inferred)

Each node contains these minimum fields:

```json
{
  "label": "Freeze loop evals",
  "status": "pending",
  "outcome": "pending",
  "retry": {"attempts": 0, "max": 2},
  "respawn": {"generation": 0, "intent": null},
  "evidence": []
}
```

`label` is the canonical human-readable text from this registry. Template labels use the decimal index verbatim.
The ID prefix `S*`, `U*`, `J*`, or `G*` identifies the node type. (inferred)

The core owns `respawn.generation`, a non-negative integer. `respawn.intent` is `null` or `{ "generation": <integer>, "reason": <nonblank string> }`.
It records the plan to start a new provider worker for that generation. It records no worker or verification-record pointer. (inferred)
The provider owns the optional `graph_role` metadata for dispatch. It is not a canonical graph field. (inferred)

The core accepts only these nine status or result tokens:
`pending`, `ready`, `running`, `blocked`, `done`, `skipped`, `failed`, `hard-stop`, and `stale`. (verified)

In the graph file, `done` and `skipped` are terminal success statuses. The `hard-stop` status is a terminal error.
The `stale` status is not a success and cannot release a dependency.
The stored `pending`, `ready`, `running`, and `blocked` statuses are non-terminal. (verified)

The core accepts `failed` only as a `record_wave` result for work that can retry. Validation rejects persisted `failed` as a node status in new v3 graph data.
In the same atomic change, the core increments `retry.attempts`. It sets the node to `pending`, or `hard-stop` if the increment exhausts `retry.max`. (verified)

A `stale` result from `record_wave` needs a `stale_check` object. Its `checked` field must be boolean `true`.
Its `method` and `result` must be nonblank strings that record the check that found the work stale.
The core persists `stale`, clears the active wave, and blocks loop end.
Stale work cannot retry automatically, release a dependency, or complete. (inferred)

Only `respawn_stale(node_id, reason)` can make a stored `stale` node eligible to retry.
The stable node must be `stale` and keep a correct `stale_check`. `active_wave` must be `null`. `reason` must be nonblank.

The core increments `respawn.generation`, records `respawn.intent` with that generation and `reason`, and keeps the stale audit records and history.
It sets the same stable node to `pending` without an increment to `retry.attempts`.
It adds no node, changes no edge or join, and starts no worker.

At the next `begin_wave` for the node, the adapter must give the worker a new provider-native identity for the recorded respawn generation.
Validate it before sending normalized records to `record_wave`. Worker and record pointers are optional before the worker starts, and the adapter does not record them then. (inferred)

`hard_stop(node_id, reason)` is a core operation for a replacement that the adapter cannot prepare or validate.
Use an existing node. Its status must be other than `done` or `skipped`. The `reason` must be nonblank.
The core persists `hard-stop` with the `reason` and keeps the topology unchanged.

If the node is in an active wave, the core removes only that unstarted node. Other active nodes stay in the wave.
If no nodes stay, the core clears `active_wave`.
This permits the core to record less than a complete wave if the adapter cannot prepare or validate a worker before dispatch.
Provider adapters must not change canonical graph fields directly. (inferred)

`edges` is an array of `{ "from": "<node-id>", "to": "<node-id>" }`. Each ID must name an existing node. An edge cannot connect a node to itself. (verified)
`joins` is an object with the join node ID as key. Each entry must use that key in `id`:

```json
"J2": {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"], "released": false}
```

The join key, `join.id`, and the corresponding node ID must have the same value. (inferred)
A join releases only if each input has a terminal success status. (verified)

An active wave is `null` or an object like this:

```json
{"wave_id": "wave-3", "revision": 7, "nodes": ["S2.5", "S2.6"]}
```

`active_wave.wave_id` is the only wave identifier in the canonical contract. (verified)
The core changes nodes or releases joins only after it gets a result for each node in that wave and no other nodes. (verified)

### Operations and invariants

The core has this minimal semantic API: `validate`, `ready`, `begin_wave`, `record_wave`, `respawn_stale`, `hard_stop`, `inspect`, and `can_complete`. (inferred)
Before each change, it validates identity, topology, retry limits, status vocabulary, active-wave consistency, and join consistency. (inferred)

`begin_wave` selects all non-join nodes that can start independently. It uses a stable sequence by node ID, marks them `running`, and records one `active_wave`. (inferred)

`record_wave` accepts only the matching `wave_id` and the complete set of active nodes. If it rejects a record, the graph stays unchanged. (verified)
`can_complete` accepts only the canonical graph. It gives `eligible` or a sequence of conditions that block it. It ignores `work_units`. (inferred)

`work_units` is optional. It has its own contract apart from `graph.nodes`. Schema v3 uses the same strict object contract for each provider:
`{ "<unit-id>": { "status": "pending" | "in-progress" | "blocked" | "done" | "dropped", "dropped_reason"?: "..." } }`.
If there is no field, or if the field is `null` or an empty object, the optional check succeeds.
A nonempty value must be an object with unit IDs as keys and objects as entries.

For the `work_units` check to succeed, each entry must be `done` or `dropped` with a nonblank `dropped_reason`.
An array, malformed object or entry, unknown status, or `dropped` without a nonblank `dropped_reason` blocks loop end.
Codex and the Claude adapter and hook apply this v3 contract. The aligned runtime rejects the v1/v2 schemas that let Claude accept arrays.

To end the loop, the graph and the provider's `work_units` must each qualify.
Then the native provider checks its verification records, evals, proofs, and retrospectives.
Adapters must not map or reconcile `work_units` to nodes in the graph. (inferred)

## Component boundaries and ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| Canonical Python core | Contract validation and changes to the graph | Files, locks, dispatch, provider routing, transcripts, raw verification records |
| Claude adapter | Claude envelope mapping, locks and atomic writes, record binding, eval/proof/retro gates, `Agent` handoff, Claude hooks | Codex APIs or records |
| Codex adapter | Codex envelope mapping, locks and atomic writes, record binding, eval/proof/retro gates, `spawn_agent` handoff, Codex hooks | Claude APIs or records |
| Contract fixtures and parity tests | Provider-neutral semantic inputs and expected outputs | Provider dispatch simulation as a shared runtime |

Provider adapters give the core only normalized pointers to verification records that the semantic contract needs.
Each provider makes, validates, and keeps its own raw records and transcript material. (inferred)
A provider adapter can add its own fields in other namespaces. It must not change canonical semantic fields or status meanings. (inferred)

## Packaging and clean-break compatibility

The only maintained source is `packages/graph-semantics/`. The providers must not keep their own forks. (inferred)
Change the existing `install.sh` to make copies at `skills/agentic-loop/scripts/graph_semantics.py` and `packages/codex/skills/agentic-loop/scripts/graph_semantics.py` before provider installation.
The installer did not do this at the time of this design. Use only the installer to supply copies.

The installer must compare each copy with the source using `cmp`. Tests and CI must do the same check.
Do not edit generated copies by hand. (inferred)

The core must not import provider packages or invoke provider commands. (inferred)
This lets you install each provider plugin independently with one maintained semantic implementation. (inferred)

This is a clean break for new graph files. (verified)
Keep v1/v2 files unchanged. The aligned runtime rejects them. It makes no promise of compatibility with earlier readers.
There is no dual-write, automatic conversion, or mixed-version wave. (inferred)

## Concurrency and atomicity

Each provider owns its existing graph path resolution and locks. (verified)
With the lock held, read the current file, invoke the pure core operation, validate the result, and replace the file atomically. (inferred)
The core needs results for the complete wave before it writes them. The provider lock prevents two writers from accepting the same wave. (inferred)

Only one orchestrator can change a given graph file at a time. (verified)
Providers share no graph file or scheduler. The design needs no cross-provider locks. (inferred)

## Python quality contract

The same strict quality gate must accept all Python files before the work is complete.
This includes the five existing Python files and the files from migration.
Do not waive or keep an existing violation. (verified)

`pyproject.toml` must be the authoritative Python tool configuration. The strict pre-commit quality gate must run these checks:

- Ruff with PEP 8, import sorting, modernization, bugbear, simplification, type hints, naming, and Google-style PEP 257 docstring rules.
- Black formatting.
- Pyright strict typing.
- mypy strict typing.

If a mandatory Python tool is unavailable, strict mode must stop with an error. Do not downgrade to advisory output.
These are development checks. The graph-semantic runtime uses only the Python standard library. (inferred)

Write complete Google-style docstrings for public Python modules, classes, functions, and methods.
For private code, write a docstring only if the typed signature and name do not make the contract clear.
Use comments for a durable purpose, constraint, safety property, or non-obvious trade-off.
Do not narrate code, cite temporary sessions, or keep commented-out code.
An inspection must check PEP 20 too, because a formatter cannot prove compliance. (inferred)

For the quality baseline, first list all current violations and correct them.
Then add a regression test that shows the commit gate rejects a representative violation.
Run the same strict gate in each subsequent migration phase. (verified)

## Test strategy

`packages/tests/provider_graph_parity.test.sh` keeps its existing provider-local checks for raw records. (verified)
The canonical fixture corpus is the authoritative provider-neutral contract for core and adapter semantics. It does not examine raw provider records. (inferred)

- Test correct topology, malformed or unknown pointers, all nine statuses, and readiness in the core.
  Test fan-out, join release, and the full active-wave match.

- Test retry exhaustion, all `stale_check` fields, `respawn_stale` generation and intent with unchanged topology, and `hard_stop` preconditions.
  Test eligibility to complete and confirm that refusal does not change the graph. (inferred)
- Run the same frozen corpus through the core and each adapter.
  Canonical graph outputs and semantic error outputs must agree byte for byte. (inferred)
- Keep provider-local tests for raw-evidence binding, transcripts, locks, hooks, and native dispatch.
  The canonical corpus must not normalize or examine raw provider records. (verified)
- Keep a negative control with an incorrect active-wave result set. Show that the canonical corpus rejects it. (verified)
- Test schema-v3 `work_units` through each adapter. A missing field, `null`, or an empty object succeeds.
  The `done` status succeeds. The `dropped` status succeeds with a nonblank `dropped_reason`.
  Arrays, malformed entries, unknown statuses, and `dropped` without a nonblank `dropped_reason` block loop end. (inferred)

## Implementation work units and dependencies

1. Set the Python quality baseline before implementation. Configure the quality gate, correct all existing Python violations, and show that the gate rejects representative violations. (verified)
2. Freeze the schema-v3 canonical fixture corpus. Check IDs, labels, join IDs, accepted tokens, and refusal of persisted `failed`.
   Check all `stale_check` fields, `respawn_stale` generation and intent, `hard_stop`, provider `work_units` eligibility, and `wave_id`. (inferred)
3. Move the pure core to the one maintained package. Use the frozen corpus for direct unit tests. Do this after 1 and 2. (inferred)
4. Add the thin Claude adapter. Keep its native locks, records, hooks, and `Agent` handoff. Do this after 1, 2, and 3. (inferred)
5. Add the thin Codex adapter. Keep its native records, hooks, and `spawn_agent` handoff. Do this after 1, 2, and 3. (inferred)
6. Package the one source in the two standalone provider bundles. Run parity tests, provider-local tests, and negative controls. Do this after 4 and 5. (inferred)

Steps 4 and 5 can run in parallel after step 3. Steps 1, 2, 3, and 6 are serial gates. (inferred)

## Risks and rollback

| Risk | Mitigation | Rollback |
| --- | --- | --- |
| Adapter translation hides a semantic difference | Frozen fixtures and authoritative parity results | Revert the two adapters. Keep historical files unchanged. The aligned runtime rejects them. |
| Providers share native records by accident | The core has no transcript or record I/O. Local tests keep ownership checks. | Remove the adapter mapping that caused the problem. Do not add records to the core. |
| Concurrent writes give invalid graph data | Provider lock spans the pure-core operation and atomic replacement | Disable the new adapter path before conversion. Keep historical graph files unchanged. |
| Bundle copy differs from maintained source | Assembly equivalence check in CI | Build the bundles again from the one source. Do not patch a generated copy. |

Rollback does not rewrite schema-v3 graph files automatically.
If a provider reads a v3 file after rollback, it must give a clear error. Use the implementation that made the file to regain compatibility. (inferred)

## Acceptance criteria

- Keep only one Python graph-semantic source. Claude and Codex have no hand-maintained semantic forks. (inferred)
- New canonical graph files use schema version 3 and root `revision: 1`.
  They use the authoritative ID grammar and label registry and all nine accepted status or result tokens.
  They reject persisted `failed` and check persisted `stale`. They use `active_wave.wave_id` and require the join key to equal `join.id`. (inferred)
- Claude and Codex adapters each use their own native dispatch, records, hooks, and locks. They do not invoke the other provider. (verified)
- No shared scheduler, routing, transcript parsing, or owner of raw records. (verified)
- `work_units` keeps its own contract apart from `graph.nodes`. (verified)
- The frozen canonical corpus succeeds for the core and the two adapters. The `provider_graph_parity` checks for raw records stay provider-local.
  The active-wave negative control gives a negative result. (inferred)
- `install.sh` makes the two generated copies before provider installation.
  The installer and test or CI checks compare them with `packages/graph-semantics/` using `cmp`. (inferred)
- Keep historical files unchanged. The aligned runtime rejects v1/v2. (verified)
- All existing and migrated Python files satisfy the quality contract. Do not add to the Python waiver lists. (verified)
- The inventory has a frozen test or provider-local assertion for each retired semantic path.
  Keep all functions and remove the legacy compatibility branches. (verified)

## Did Not Verify

- Wiki was queried; it records historical provider independence, which this approved decision deliberately narrows. (verified)
- I did not inspect a future package layout, installer, generated bundle format, or test output; this document specifies them as implementation requirements. (verified)
- I did not execute tests because this task creates a design specification only and the user prohibited source/test changes. (verified)
