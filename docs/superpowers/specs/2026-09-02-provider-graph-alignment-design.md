# Provider graph-alignment design

## Problem and decision

The Claude graph contract is defined by `skills/agentic-loop/loop-state.md` and `skills/agentic-loop/execution-graph.md`, while the Codex contract is implemented in `packages/codex/skills/agentic-loop/scripts/graph.py`. (verified) Their current state shapes differ, including the active-wave identifier. (verified)

**Decision.** New graph state is interpreted and mutated by one canonical Python graph-semantic core. Claude and Codex call it through thin provider-local adapters. The core owns only graph validation, readiness, wave transitions, joins, retry transitions, and graph-completion eligibility. (verified)

This supersedes the wiki's historical independent-runtime policy for graph semantics only. (inferred) It preserves the safety purpose of that policy by keeping scheduling, routing, transcript parsing, raw evidence, hooks, locking integration, and provider dispatch ownership local to each provider. (verified)

## Non-goals

- No shared scheduler, daemon, worker launcher, routing table, or provider selection policy. (verified)
- No shared transcript parser, evidence collector, evidence-store schema, or raw evidence ownership. (verified)
- No change to Claude `Agent` dispatch, Claude evidence, Claude locks, or Claude hooks. (verified)
- No change to Codex `spawn_agent` dispatch, Codex evidence, or Codex hooks. (verified)
- No reconciliation between `work_units` and `graph.nodes`. They remain separate views with separate lifecycle consumers. (verified)
- No migration, rewriting, or reinterpretation of historical state files. (verified)
- No grandfathered semantic branch, legacy fallback, compatibility shim,
  dual-reader, dual-writer, automatic conversion, or mixed-version wave.
  (verified)

## Functional preservation and clean break

The migration must preserve every existing provider capability and safety
property: validation, readiness, wave transitions, joins, retry exhaustion,
stale handling, hard stops, locks, atomic writes, native dispatch, raw-evidence
binding, evaluation gates, proof gates, retrospective gates, and completion
gates. A refactor is not accepted because tests are green if it silently drops
one of those behaviours. (verified)

The preserved behaviour is implemented once in the aligned schema-v3 contract,
not retained through legacy compatibility. Before deleting or replacing a
semantic path, the implementation must identify its consumers, cover its
observable behaviour in the frozen corpus or provider-local tests, and remove
the obsolete path in the same change. Historical v1/v2 state files are data,
not a compatibility surface: leave them untouched and reject them clearly.
(verified)

## Canonical graph contract

### Scope and versioning

The canonical format is `schema_version: 3`. (inferred) It applies only when a provider creates a new state after this change. Existing `schema_version: 1` and `2` files remain untouched, but the aligned runtime must reject them with a clear compatibility error. This makes no promise about old-reader compatibility: there is no migration, dual-write, conversion, or mixed-version wave. (inferred)

The graph core receives a complete state document and returns a complete proposed state document or a validation error; it does not locate files, acquire locks, read transcripts, or perform I/O. (inferred)

### Root graph fields

`progress.json` retains provider-owned root fields such as `session_id`, `loop_id`, `revision`, lifecycle `status`, `work_units`, and completion artifacts. (verified) A new canonical root starts with `revision: 1`. (inferred) Its canonical `graph` value is:

```json
{
  "nodes": {},
  "edges": [],
  "joins": {},
  "active_wave": null,
  "hard_stop": null
}
```

`graph.nodes` is keyed only by Claude-derived stable IDs. The authoritative grammar is `S-2|S-1|S0|S0.4|S0.5|S1|S2|S2.5|S2.6|J2|S2.7a|S2.7b|S2.7c|S2.7d[i]|S2.7e|S2.8|J2.8|U3[i]|U4[i]|U4b-review[i]|U5[i]|U5-repair[i]|U6[i]|U7/8[i]|U4b-merge-gate[i]|U10-respawn[i]|J12-all-units|G10|G11|G12|S9-wiki|S9-docs|S13-proof|S13-retro|S13-complete`, where every `[i]`, including `S2.7d[i]`, is a positive base-10 work-unit index. `S*` are single-run steps, `U<i>*` are per-work-unit steps, `J*` are joins, and `G*` are cross-cutting guards. (verified) IDs are durable graph keys, never display text. (inferred)

The authoritative display-label registry, with its exact Claude source phase/action mapping, is:

| ID template | Display label | Exact Claude source phase/action |
| --- | --- | --- |
| `S-2` | `Initialize loop state` | `Stub state` |
| `S-1` | `Improve prompt` | `Improve prompt` |
| `S0` | `Read authorization envelope` | `Read envelope` |
| `S0.4` | `Record model cost` | `Model-cost notice` |
| `S0.5` | `Apply operating rules` | `Operating rules` |
| `S1` | `Plan work` | `Plan` |
| `S2` | `Run preflight` | `Plan` — pre-flight agent result, wiki/theme intake, retro lessons, and clean-base check |
| `S2.5` | `Resolve design fork` | `S2` design scout |
| `S2.6` | `Choose disposition` | `S2` disposition scout |
| `J2` | `Preflight decisions joined` | `S2.5` and `S2.6` joined |
| `S2.7a` | `Write specification` | durable `spec.md` |
| `S2.7b` | `Write implementation plan` | durable `plan.md` |
| `S2.7c` | `Freeze loop evals` | loop-scope evals frozen |
| `S2.7d[i]` | `Freeze unit i evaluation` | PR-scope evals frozen for unit `i` |
| `S2.7e` | `Freeze proof plan` | `proof.json` or no-executable disposition |
| `S2.8` | `Assign model roles` | recorded model role for every build unit |
| `J2.8` | `Implementation ready` | first eligible unit inputs joined |
| `U3[i]` | `Build unit i` | worker produced unit `i` artifact/OPEN PR |
| `U4[i]` | `Verify unit i artifact` | orchestrator artifact check |
| `U4b-review[i]` | `Review unit i` | required review and post-review artifact |
| `U5[i]` | `Diagnose unit i` | source-of-truth premise confirmed and diagnosis disconfirmed |
| `U5-repair[i]` | `Repair unit i` | distinct fix attempt applied and verified |
| `U6[i]` | `Resolve continuation` | in-scope continuation decision resolved |
| `U7/8[i]` | `Push or deploy unit i` | stack-specific push/deploy tactic |
| `U4b-merge-gate[i]` | `Merge gate unit i` | exact-head review/eval/integrity gate |
| `U10-respawn[i]` | `Respawn unit i` | new versioned worker and fresh dispatch |
| `J12-all-units` | `All units joined` | every unit merge gate passed |
| `G10` | `Guard replacement worker` | replacement worker names versioned |
| `G11` | `Check confidence labels` | worker prompts and reports labelled |
| `G12` | `Fresh artifact check` | fresh artifact recheck at boundary |
| `S9-wiki` | `Update wiki` | clustered wiki ingest and lint |
| `S9-docs` | `Sync docs` | `/sync-docs` audit and triage |
| `S13-proof` | `Run frozen proofs` | frozen proof commands ran and passed |
| `S13-retro` | `Write loop retrospective` | Phase 13 report and artifacts written |
| `S13-complete` | `Complete loop` | `Complete loop` |

Display labels are deliberately human-readable and need not repeat the internal source title verbatim; the source-mapping column is the traceability contract. (inferred)

Each node contains at least:

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

`label` is the canonical human-readable text from this registry; template labels substitute the decimal index verbatim. Node kind is determined by the ID prefix: `S*`, `U*`, `J*`, or `G*`. (inferred) `respawn.generation` is a non-negative core-owned integer and `respawn.intent` is either `null` or `{ "generation": <integer>, "reason": <nonblank string> }`; it records a requested fresh provider worker for that generation, never a provider worker or evidence reference. (inferred) `graph_role` is optional provider-owned dispatch metadata, not a canonical graph field. (inferred)

The nine-token accepted state/result vocabulary is exactly: `pending`, `ready`, `running`, `blocked`, `done`, `skipped`, `failed`, `hard-stop`, and `stale`. (verified) `done` and `skipped` are terminal-success persisted statuses. `hard-stop` is a terminal failure persisted status; `stale` is persisted non-success and cannot release a dependency. `pending`, `ready`, `running`, and `blocked` are non-terminal persisted statuses. (verified)

`failed` is accepted only as a `record_wave` result for retryable work, never as a persisted canonical node status in newly-created v3 state. In the same atomic transition, the core increments `retry.attempts` and maps the node to `pending`; if the increment exhausts `retry.max`, it maps the node to `hard-stop`. Validation rejects a persisted `failed` status in newly-created v3 state. (verified) A `stale` `record_wave` result is accepted only with a `stale_check` object whose `checked` is boolean `true` and whose `method` and `result` are nonblank strings recording the check that made it stale. The core persists `stale`, clears the active wave, and makes completion ineligible; stale work cannot automatically retry, release a dependency, or complete. (inferred)

`respawn_stale(node_id, reason)` is the only permitted recovery of a persisted `stale` node. Its preconditions are: the stable node is `stale`; it retains a valid `stale_check`; `active_wave` is `null`; and `reason` is nonblank. The core increments `respawn.generation`, records `respawn.intent` with that generation and reason, preserves the stale audit evidence/history, sets the same stable node to `pending`, and does not increment `retry.attempts`. It creates no node, changes no edge or join, and does not dispatch. At the later `begin_wave`, the adapter must allocate a fresh provider-native worker identity for the recorded respawn generation and validate it before it sends normalized evidence to `record_wave`; worker and evidence references are neither required nor recorded before dispatch. (inferred)

`hard_stop(node_id, reason)` is a core-owned operation for a replacement that cannot be prepared or validated. It requires an existing node, a nonblank reason, and a node that is not `done` or `skipped`; it persists `hard-stop` with the reason and leaves topology unchanged. If the node is in an active wave, the core removes only that unstarted node from the wave and retains the remaining active nodes; if none remain, it clears `active_wave`. This is the explicit exception to normal complete-wave recording for a worker that could not be prepared or validated before dispatch. No provider adapter may mutate canonical graph fields directly. (inferred)

`edges` is an array of `{ "from": "<node-id>", "to": "<node-id>" }`. Both IDs must exist and an edge may not self-loop. (verified) `joins` is an object keyed by the join node ID; every entry must repeat that key in `id`:

```json
"J2": {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"], "released": false}
```

The join key, `join.id`, and the corresponding node ID must be identical. (inferred) A join releases only when every input is terminal-success. (verified)

An active wave is either `null` or:

```json
{"wave_id": "wave-3", "revision": 7, "nodes": ["S2.5", "S2.6"]}
```

`active_wave.wave_id` is the sole wave identifier in the canonical contract. (verified) The core requires a complete, exact result set for that wave before it transitions any node or releases joins. (verified)

### Operations and invariants

The core exposes a minimal semantic API: `validate`, `ready`, `begin_wave`, `record_wave`, `respawn_stale`, `hard_stop`, `inspect`, and `can_complete`. (inferred) It validates identity, graph topology, retry bounds, status vocabulary, active-wave consistency, and join consistency before every mutation. (inferred)

`begin_wave` selects all currently ready independent non-join nodes in stable node-ID order, marks them `running`, and records one `active_wave`. (inferred) `record_wave` accepts only the matching `wave_id` and exactly the active node set; a rejected record leaves state unchanged. (verified) `can_complete` accepts the canonical graph only and returns either `eligible` or ordered blocking reasons; it ignores `work_units`. (inferred)

`work_units` is optional and independent of `graph.nodes`. Schema-v3 requires the same strict object contract for both providers: `{ "<unit-id>": { "status": "pending" | "in-progress" | "blocked" | "done" | "dropped", "dropped_reason"?: "..." } }`. An absent, `null`, or empty object passes the optional predicate. A nonempty value must be an object keyed by unit ID with object entries; every entry must be `done`, or `dropped` with a nonblank `dropped_reason`, for final `work_units` eligibility. Any array, malformed object or entry, unknown status, or unreasoned `dropped` blocks final completion. Codex adopts this v3 contract and the Claude adapter/hook carries it for v3; Claude's historical v1/v2 array tolerance is irrelevant because aligned runtime rejects those schemas. Final completion requires both graph eligibility and this independent provider predicate, followed by the provider-native evidence, evaluation, proof, and retrospective gates; adapters must not map or reconcile `work_units` to graph nodes. (inferred)

## Component boundaries and ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| Canonical Python core | Contract validation and graph-state transitions | Files, locks, dispatch, provider routing, transcripts, raw evidence |
| Claude adapter | Claude state envelope mapping, lock/atomic-write integration, evidence binding, eval/proof/retro completion gates, `Agent` dispatch handoff, Claude hooks | Codex APIs or evidence |
| Codex adapter | Codex state envelope mapping, lock/atomic-write integration, evidence binding, eval/proof/retro completion gates, `spawn_agent` handoff, Codex hooks | Claude APIs or evidence |
| Contract fixtures and parity tests | Provider-neutral semantic inputs and expected outputs | Provider dispatch simulation as a shared runtime |

Provider adapters pass the core only normalized semantic evidence references needed by the state contract; each provider creates, validates, and retains its own raw evidence and transcript material. (inferred) A provider adapter may add provider-owned fields outside the canonical graph namespace, but it may not change canonical semantic fields or status meanings. (inferred)

## Packaging and clean-break compatibility

The maintained source of the core is exactly `packages/graph-semantics/`; neither provider owns a hand-maintained fork. (inferred) Implementation must modify the existing `install.sh` to materialize copies at `skills/agentic-loop/scripts/graph_semantics.py` and `packages/codex/skills/agentic-loop/scripts/graph_semantics.py` before provider installation; the current installer does not do this. Installer-supported delivery is the only delivery path. The installer must verify each generated copy with `cmp` against the source, and test/CI must repeat that verification. Generated copies are never hand-edited. (inferred)

The core must not import provider packages or invoke provider commands. (inferred) This permits independently installed provider plugins while avoiding two maintained semantic implementations. (inferred)

This is a clean break for newly created graph state, not a migration project. (verified) v1/v2 files remain untouched but are rejected by the aligned runtime; there is no old-reader compatibility promise, dual-write, automatic conversion, or mixed-version wave. (inferred)

## Concurrency and atomicity

Each provider remains responsible for its existing state-path resolution and locking mechanism. (verified) It must lock around: read current state, call the pure core operation, validate the result, and atomically replace the state file. (inferred) The core's complete-wave requirement prevents partial result commits; the provider lock prevents competing writers from both accepting the same wave. (inferred)

Only one orchestrator may mutate a given state file at a time. (verified) The design does not introduce cross-provider locks because providers do not share a state file or scheduler. (inferred)

## Python quality contract

Every Python file in the repository, including the five pre-existing files and
all migration output, must pass the same hard quality gate before this work is
complete. No existing Python violation is grandfathered, waived, or converted
into a permanent exception. (verified)

`pyproject.toml` must be the authoritative Python-tool configuration. The
strict pre-commit quality path must require: Ruff linting with PEP 8,
import-order, modernization, bugbear, simplification, annotation, naming, and
Google-style PEP 257 docstring rules; Black formatting; Pyright strict typing;
and mypy strict typing. Missing required Python tools must fail strict mode,
not downgrade to advisory output. The graph-semantic runtime itself remains
standard-library-only; these are development checks, not runtime imports.
(inferred)

Public Python modules, classes, functions, and methods require complete
Google-style docstrings. Private implementation details receive a docstring
only when their contract is not obvious from a typed signature and name.
Comments must explain a durable why, constraint, safety property, or
non-obvious trade-off; they must not narrate code, cite a transient session, or
leave commented-out code. PEP 20 compliance is a review requirement alongside
the mechanical checks because no formatter can prove it. (inferred)

The quality baseline work must first inventory every current violation, repair
all of them, then add regression coverage that makes a representative violation
fail the commit gate. Every later migration phase runs the same strict gate.
(verified)

## Test strategy

`packages/tests/provider_graph_parity.test.sh` remains provider-local for its existing raw-evidence checks. (verified) A separate canonical fixture corpus is the authoritative provider-neutral contract seam, limited to core and adapter semantics; it does not inspect raw provider evidence. (inferred)

- Test the core directly for valid topology, malformed/unknown references, nine-status validation, readiness, fan-out/join release, exact wave matching, retry exhaustion, exact `stale_check` validation, `respawn_stale` generation/intent and unchanged topology, `hard_stop` preconditions, completion eligibility, and rejected-state immutability. (inferred)
- Run the same frozen canonical fixture corpus through the core and each adapter and require byte-equal canonical graph output and identical errors for semantic failures. (inferred)
- Keep provider-local tests for raw-evidence binding, transcript handling, locks, hooks, and native dispatch. The canonical corpus must not normalize or inspect raw provider evidence. (verified)
- Keep a negative control that breaks exact active-wave result matching and proves the canonical fixture seam fails. (verified)
- Test the schema-v3 `work_units` predicate through both adapters: absent, `null`, and empty object succeed; `done` and reasoned `dropped` succeed; arrays, malformed entries, unknown statuses, and unreasoned `dropped` block final completion. (inferred)

## Implementation work units and dependencies

1. Establish the Python quality baseline: configure and enforce the quality contract, remediate every existing Python violation, and prove the commit gate rejects representative violations. This is the prerequisite for all implementation. (verified)
2. Freeze the schema-v3 canonical fixture corpus with ID, label, join-ID, accepted-token, persisted-`failed` rejection, exact `stale_check`, `respawn_stale` generation/intent, `hard_stop`, provider `work_units` eligibility, and `wave_id` assertions. (inferred)
3. Extract the pure core into the single maintained package and direct unit tests at the frozen corpus. Depends on 1 and 2. (inferred)
4. Add the Claude thin adapter, preserving its native locks, evidence, hooks, and `Agent` handoff. Depends on 1, 2, and 3. (inferred)
5. Add the Codex thin adapter, preserving its native evidence, hooks, and `spawn_agent` handoff. Depends on 1, 2, and 3. (inferred)
6. Package the one source into both standalone provider bundles and run parity, provider-local tests, and negative controls. Depends on 4 and 5. (inferred)

Steps 4 and 5 may proceed in parallel after step 3; steps 1, 2, 3, and 6 are serial gates. (inferred)

## Risks and rollback

| Risk | Mitigation | Rollback |
| --- | --- | --- |
| Semantic drift hidden by adapter translation | Frozen fixtures and authoritative parity results | Revert both adapters; leave historical files untouched; aligned runtime rejects them |
| Provider-native evidence becomes shared by accident | Core has no transcript/evidence I/O; local tests retain ownership checks | Remove the offending adapter mapping; do not add evidence to the core |
| Concurrent writes produce invalid state | Provider lock surrounds pure-core transition and atomic replacement | Disable the new adapter path before any state conversion; historical states remain untouched |
| Bundle copy drifts from maintained source | Assembly equivalence check in CI | Rebuild bundles from the single source; never patch a generated copy |

Rollback never rewrites schema-v3 state automatically. A provider encountering such state after rollback must fail clearly and require the implementation that created it to restore compatibility. (inferred)

## Acceptance criteria

- Exactly one maintained Python graph-semantic source exists; no hand-maintained Claude/Codex semantic forks remain. (inferred)
- New canonical graph states use schema version 3, root `revision: 1`, the authoritative ID grammar and label registry, accepted nine-token state/result vocabulary, persisted-`failed` rejection, persisted-`stale` checks, `active_wave.wave_id`, and join key/`join.id` equality. (inferred)
- Claude and Codex adapters use their native dispatch, evidence, hooks, and locking; neither invokes the other provider. (verified)
- No shared scheduler, routing, transcript parsing, or raw-evidence owner is introduced. (verified)
- `work_units` remains independent from `graph.nodes`. (verified)
- The frozen canonical fixture corpus passes for the core and both adapters; provider-local `provider_graph_parity` raw-evidence checks remain provider-local; the active-wave negative control fails. (inferred)
- `install.sh` materializes both generated copies before provider installation, and installer plus test/CI `cmp`-verify them against `packages/graph-semantics/`. (inferred)
- Historical states are neither migrated nor rewritten, and the aligned runtime rejects v1/v2. (verified)
- Every existing and migrated Python file passes the enforced Python quality contract; no Python exception list grows. (verified)
- The capability inventory has a frozen test or provider-local acceptance
  assertion for every retired semantic path; no functional loss or legacy
  compatibility branch remains. (verified)

## Did Not Verify

- Wiki was queried; it records historical provider independence, which this approved decision deliberately narrows. (verified)
- I did not inspect a future package layout, installer, generated bundle format, or test output; this document specifies them as implementation requirements. (verified)
- I did not execute tests because this task creates a design specification only and the user prohibited source/test changes. (verified)
