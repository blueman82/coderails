# Provider graph-alignment implementation plan

## Purpose and fixed boundaries

Implement the approved schema-v3 graph contract from
`docs/superpowers/specs/2026-09-02-provider-graph-alignment-design.md` without
creating a shared installed runtime. `packages/graph-semantics/` is the one
maintained Python source; `install.sh` materializes it into the independently
installable Claude and Codex bundles. (verified)

The core owns only pure validation and state transitions. Provider adapters
retain state paths, locks, atomic writes, native dispatch, transcript parsing,
raw evidence, hooks, and provider completion gates. (verified)

### Protected files and non-goals

- Preserve the approved untracked design document; do not rewrite it during
  implementation. (verified)
- Do not add a scheduler, daemon, shared worker launcher, provider router,
  shared transcript parser, or shared raw-evidence store. (verified)
- Do not change Claude `Agent` dispatch or Codex `spawn_agent` dispatch. (verified)
- Do not map `work_units` to `graph.nodes`, migrate v1/v2 files, dual-write,
  or run mixed schema-version waves. (verified)
- Do not hand-edit either generated bundle copy:
  `skills/agentic-loop/scripts/graph_semantics.py` or
  `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`. (verified)
- Do not change Factory code or behaviour. (verified)

## Worktree ownership and order

| Phase | Owner/worktree | Prerequisite | Deliverable |
| --- | --- | --- | --- |
| 1. Freeze fixtures | Codex, integration worktree | none | Frozen provider-neutral semantic corpus and runner |
| 2. Extract core | Codex, integration worktree | Phase 1 | `packages/graph-semantics/` pure Python core |
| 3A. Claude adapter | Claude headless, Claude-only worktree | Phases 1–2 | Python adapter behind existing Claude Bash/hook boundaries |
| 3B. Codex adapter | Codex, Codex-only worktree | Phases 1–2 | `graph.py` becomes an I/O adapter over the core |
| 4. Materialize and parity | Codex, integration worktree | 3A and 3B | Installer generation and cross-adapter corpus parity |
| 5. Native acceptance | Both providers, integration worktree | Phase 4 | Provider-native acceptance evidence |

Phases 1, 2, 4, and 5 are serial gates. Only 3A and 3B run in parallel. (verified)

## Phase 1 — freeze the canonical fixture corpus

1. Create `packages/graph-semantics/fixtures/` and place each canonical input,
   operation request, expected canonical output, or expected error in a
   deterministic JSON fixture. Add `packages/tests/graph_semantics_fixtures.test.sh`
   as the one runner for the corpus. (inferred)
2. Freeze fixtures before extracting code. Cover the exact schema-v3 contract:
   - rejected schema versions 1 and 2, root revision `1`, the complete stable
     ID grammar, and the human-label registry;
   - all nine accepted result/state tokens, while rejecting persisted
     `failed` in new state;
   - valid/invalid topology, self-edges, cycles, join-key/`join.id` mismatch,
     ready ordering, fan-out, and all-input join release;
   - `begin_wave` creates `active_wave.wave_id`, marks its exact node set, and
     rejects a second active wave;
   - `record_wave` rejects partial, extra, stale, or wrong-wave results without
     changing the input state; it retries `failed` to `pending` or
     `hard-stop` on exhaustion;
   - `stale_check` validation; `respawn_stale` generation/intent, unchanged
     topology, and no automatic dispatch; and `hard_stop` preconditions;
   - `can_complete` ordered blockers and the independent v3 `work_units`
     predicate: absent, `null`, and `{}` pass; `done` and reasoned `dropped`
     pass; arrays, malformed entries, unknown statuses, and unreasoned
     `dropped` block. (verified)
3. Store a deliberate negative-control fixture with a mismatched active-wave
   result set and assert the runner fails while the source state is byte
   unchanged. (verified)
4. Keep `packages/tests/provider_graph_parity.test.sh` unchanged in purpose:
   it remains the provider-local raw-evidence/transcript test, not the
   canonical semantic corpus. (verified)

**Phase check:** `bash packages/tests/graph_semantics_fixtures.test.sh` passes;
the negative-control invocation fails; `git diff --check` passes. (inferred)

## Phase 2 — implement the pure maintained Python core

1. Add `packages/graph-semantics/graph_semantics.py` and, if needed, a small
   `__init__.py`. It must use only the Python standard library and accept a
   complete state value plus an operation request, returning a complete
   proposed state or a deterministic semantic error. It performs no file I/O,
   locking, subprocess, import of provider modules, transcript lookup, or
   evidence lookup. (verified)
2. Implement the approved minimal API in that module:
   `validate`, `ready`, `begin_wave`, `record_wave`, `respawn_stale`,
   `hard_stop`, `inspect`, and `can_complete`. Keep all canonical mutation
   within these functions. (verified)
3. Move the common state-machine behaviour currently split across Codex
   `packages/codex/skills/agentic-loop/scripts/graph.py` functions
   `_validate_state`, `_dependencies`, `_release_joins`, `_ready`, `_results`,
   `_begin_wave`, `_record_wave`, `_inspect`, and `_validate_completion` into
   this pure API. Do not move Codex `_load`, `_write`, `_locked`,
   `_authorize_dispatch`, or anything in `graph_evidence.py`. (verified)
4. Define deterministic error text/codes in the core and have the fixture
   runner compare them exactly, including immutability after rejected requests.
   The core copies before mutation so invalid input cannot be partially changed.
   (inferred)
5. Add a direct Python test entry point under
   `packages/graph-semantics/tests/` only if it complements rather than
   duplicates the frozen fixture runner; use the corpus as the source of
   truth. (inferred)

**Phase check:** run the fixture runner against the core; run
`python3 -m py_compile packages/graph-semantics/graph_semantics.py`; verify
the core imports no provider-local module with `rg`. (inferred)

## Phase 3A — migrate the Claude semantic adapter (parallel)

### Ownership

Claude headless works only in a Claude-specific worktree. Codex does not edit
those files concurrently. It retains Claude-native Bash locking, hook seams,
`Agent` handoff, progress-path resolution, and raw-evidence binding. (verified)

### Exact changes

1. Replace semantic validation/readiness/wave transition logic in
   `hooks/scripts/lib/graph_readiness.sh`,
   `hooks/scripts/lib/graph_executor.sh`, and
   `hooks/scripts/lib/graph_dispatch.sh` with thin calls to the generated
   `skills/agentic-loop/scripts/graph_semantics.py` CLI/module boundary. Keep
   each existing public shell function name and calling contract, including:
   `graph_executor_graph_valid`, `graph_executor_ready_nodes`,
   `graph_executor_apply_wave`, and the `graph_dispatch_*` functions consumed
   by skills and hook guards. (verified)
2. Retain `hooks/scripts/lib/loop_state_common.sh` as Claude’s sole state-path,
   lock, and atomic-write owner. The adapter reads the full state under that
   lock, invokes one core transition, validates its result, and atomically
   replaces the file. (verified)
3. Preserve Claude-only evidence and dispatch code, including
   `hooks/scripts/lib/graph_evidence.sh` (if used by the dispatch seam),
   `hooks/scripts/loop_dispatch_guard.sh`, and the `Agent` payload contract.
   Normalize only the semantic evidence reference passed to `record_wave`; do
   not move transcript parsing into Python core. (verified)
4. Update `skills/agentic-loop/loop-state.md`,
   `skills/agentic-loop/execution-graph.md`, and
   `skills/agentic-loop/SKILL.md` only where their documented command/state
   contract must state schema v3, `wave_id`, stable IDs, stale/respawn, and
   strict v3 `work_units`. Do not rewrite unrelated workflow prose. (inferred)
5. Update focused Claude tests rather than creating parallel replacements:
   `hooks/scripts/tests/graph_contract.test.sh`, `graph_readiness.test.sh`,
   `graph_executor.test.sh`, `graph_executor_stale_check.test.sh`,
   `graph_dispatch.test.sh`, `graph_dispatch_acceptance.test.sh`,
   `graph_dispatch_complete.test.sh`, `graph_two_unit_fanout.test.sh`, and
   `loop_stall_guard_graph_complete.test.sh`. Preserve their provider-native
   lock/evidence/hook assertions. (verified)

### Headless Claude execution

Run one bounded Claude task at a time from its Claude-only worktree:

```zsh
claude --model sonnet -p "$PROMPT" --output-format stream-json --verbose --no-session-persistence \
  | jq -r 'if .type == "assistant" then .message.content[]? | select(.type == "text") | .text elif .type == "result" then .result else empty end'
```

The prompt must name the exact Phase-3A files, prohibit Factory and Codex
edits, require `apply_patch`, and require native Claude test output. The
orchestrator retains the transcript JSON only as diagnostics and reports
deduplicated text/result output. (verified)

**Phase check:** `bash hooks/scripts/tests/graph_contract.test.sh`,
`bash hooks/scripts/tests/graph_readiness.test.sh`,
`bash hooks/scripts/tests/graph_executor.test.sh`,
`bash hooks/scripts/tests/graph_executor_stale_check.test.sh`, and the focused
dispatch/complete tests above pass from the Claude worktree. (inferred)

## Phase 3B — migrate the Codex semantic adapter (parallel)

1. Keep `packages/codex/skills/agentic-loop/scripts/graph.py` as the native
   Codex CLI/I/O adapter. Retain `_load`, `_write`, `_locked`, CLI parser,
   `main`, `transcript_cursor`, `bind_worker_evidence`,
   `validate_worker_evidence`, `validate_evals`, and
   `validate_completion_evidence`. Replace its duplicated semantic state
   functions with calls into generated `graph_semantics.py`. (verified)
2. Preserve `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` and
   `graph_identity.py` as Codex-owned evidence/task-name code. The adapter
   allocates provider-native task identity only after a core `begin_wave`, and
   for a stale respawn only in its later dispatched wave. (verified)
3. Extend the CLI in `graph.py` for core-owned `respawn-stale` and `hard-stop`
   operations, with the adapter handling its file lock and atomic replacement.
   Update only its Codex callers: `packages/codex/skills/agentic-loop/SKILL.md`,
   `packages/codex/hooks/scripts/graph_completion_guard.sh`, and
   `packages/codex/hooks/scripts/loop_dispatch_guard.sh` where the new schema
   or command contract requires it. (inferred)
4. Adapt `_complete` and `_verify_completion` so core `can_complete` gates the
   canonical graph, then Codex applies its v3 independent `work_units`
   predicate and existing native evidence/eval/proof/retro validation. Do not
   couple `work_units` to nodes. (verified)
5. Update existing Codex tests:
   `packages/tests/codex_graph_runtime_adversarial.test.sh`,
   `packages/tests/codex_graph_evidence_shapes.test.sh`,
   `packages/tests/provider_graph_lifecycle_adversarial.test.sh`, and
   `packages/tests/provider_graph_final_adversarial.test.sh`. Add only focused
   test cases for the v3 adapter boundary and native evidence preservation.
   (inferred)

**Phase check:** run those four tests plus
`python3 -m py_compile packages/codex/skills/agentic-loop/scripts/graph.py`
from the Codex worktree. (inferred)

## Phase 4 — installer materialization and semantic parity

1. Modify only the existing `install.sh` delivery flow to materialize the
   maintained `packages/graph-semantics/graph_semantics.py` into exactly:
   - `skills/agentic-loop/scripts/graph_semantics.py`
   - `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`

   Do this before either provider’s installation logic. Use existing Bash 3.2
   compatible shell style and atomic-copy patterns where available. Do not add
   a packaging framework. (verified)
2. Add a small installer helper in `install.sh` that creates parent paths,
   copies from the maintained source, and runs `cmp -s` for each destination.
   Fail installation before plugin installation if either copy differs. The
   helper is the only writer of generated copies. (inferred)
3. Extend `packages/tests/codex_installer.test.sh` and the root installer test
   surface (`hooks/scripts/tests/install_routines.test.sh` and/or
   `hooks/scripts/tests/install_mode_sweep.test.sh`, based on their existing
   HOME-sandbox ownership) to prove both provider install modes materialize
   byte-identical copies without mutating source. Preserve the existing
   fresh-`$HOME`, executable-mode, and macOS Bash 3.2 checks. (verified)
4. Replace schema-v2-only assumptions in
   `packages/tests/provider_graph_parity.test.sh` only as needed for v3.
   Keep its raw-evidence fixture setup and native guard checks. Add a distinct
   `packages/tests/graph_semantics_adapter_parity.test.sh` that runs every
   frozen fixture through the generated Claude and Codex adapters, strips only
   provider-owned envelope/evidence fields, and compares canonical graph output
   and semantic errors byte-for-byte. It must not simulate native dispatch or
   inspect raw evidence. (inferred)
5. Add the materialization equivalence check to the repository’s existing
   quality/CI entry point only after identifying where
   `hooks/scripts/tests/run_all.sh` and package tests are composed. Do not add
   an independent CI workflow. (inferred)

**Phase check:** run `cmp -s` from maintained source to both generated paths;
run installer sandbox tests; run both parity tests; run the active-wave negative
control and confirm it fails. (verified)

## Phase 5 — native acceptance and integration review

1. In the integration worktree, run the complete focused suite from Phases 1,
   3A, 3B, and 4, then the standard root and Codex test entry points identified
   by their existing runners. Record command, exit status, and revision. (inferred)
2. Run a Claude-native acceptance loop using the generated Claude bundle:
   inspect → begin wave → native `Agent` dispatch handoff → collect exact wave
   results → record → complete. Exercise fan-out/join, retry exhaustion, stale
   check then explicit respawn, and the strict `work_units` completion gate.
   Do not invoke Codex in that loop. (inferred)
3. Run the equivalent Codex-native acceptance loop using the generated Codex
   bundle and native `spawn_agent` handoff. Preserve Codex transcript-derived
   evidence revalidation at completion. Do not invoke Claude in that loop.
   (verified)
4. Perform two independent reviews: Claude headless reviews Codex adapter and
   integration changes; Codex reviews Claude adapter and integration changes.
   Both review only current-worktree diffs against the frozen corpus and the
   protected-boundary list. (inferred)
5. Final acceptance is blocked unless all are true: one maintained source;
   both generated copies match it; v3 fixtures pass for core and both adapters;
   provider-local raw-evidence tests pass; no v1/v2 conversion exists; no
   shared installed runtime/scheduler/dispatch/evidence path exists; and the
   two native acceptance runs pass. (verified)

## Implementation handoff checklist

- Create and freeze task evals from this plan before Phase 1 implementation.
  (verified)
- Start one native agentic-loop graph only after evals are frozen; the
  orchestrator, not workers, records the durable plan and waves. (verified)
- Keep the integration worktree owner responsible for fixture/core/installer
  merges; keep provider worktrees disjoint until Phase 4. (inferred)
- Stop before commit, push, or Factory work unless separately authorized.
  (verified)

## Did Not Verify

- The exact existing CI composition point for package and root tests; Phase 4
  must identify it before adding the required materialization check. (verified)
- Whether every current Claude graph helper has a public caller outside the
  focused tests named above; Phase 3A must search callers before deleting any
  semantic branch. (verified)
