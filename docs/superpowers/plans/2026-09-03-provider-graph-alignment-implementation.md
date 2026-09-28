# Provider graph-alignment implementation plan

> Current implementation note (2026-09-21): retain the shell rosters and earlier phase commands below as the frozen migration baseline. The clean-break amendment supersedes every instruction to execute or retain those old paths. Current delivery uses `install.py` and `scripts/installer/files.py`; current entrypoints and tests are Python, including `hooks/scripts/tests/run_all.py`, `packages/tests/test_graph_semantics_fixtures.py`, and `packages/tests/test_provider_graph_parity.py`. Follow [the component reference](../../REFERENCE.md) and [installation guide](../../../INSTALLATION.md) for operational commands. No shell wrapper or schema-v1/v2 graph reader remains.

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
- Preserve every current provider capability and safety gate, then delete the
  replaced semantic path in the same change. Do not retain a legacy fallback,
  compatibility shim, dual reader, or dual writer. (verified)
- Do not hand-edit either generated bundle copy:
  `skills/agentic-loop/scripts/graph_semantics.py` or
  `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`. (verified)
- Do not change Factory code or behaviour. (verified)

## Worktree ownership and order

## Two-provider Python clean-break amendment

This amendment is authoritative for every Coderails-owned Claude and Codex
shell path named below and supersedes earlier wording that retains a `.sh`
path. The end state is one implementation language, Python, across both
providers. No legacy Bash wrapper, compatibility fallback, dual reader/writer,
or grandfathered path remains. Claude native `Agent` and Codex native
`multi_agent_v1__spawn_agent` dispatch remain provider-native; only
provider-owned operational code changes language. (verified)

### End state and constraints

`find hooks/scripts scripts packages/codex packages/tests -type f -name '*.sh'`
returns no Coderails-owned shell path: no launcher, helper, test shim,
compatibility wrapper, or grandfathered path remains.
Each same-batch replacement preserves CLI, stdin/stdout/stderr, exit status,
timeout, environment, filesystem effects, and failure modes. Use Python
stdlib (`argparse`, `json`, `pathlib`, `subprocess`, `tempfile`, `fcntl`, and
`unittest`) first; retain existing external commands only where their current
contract requires them, and add no runtime package. Entry points use
`#!/usr/bin/env python3`; callers name `.py` paths. The maintained
`packages/graph-semantics/graph_semantics.py` remains installer-materialized
into its two generated copies; migrated operational scripts are maintained
Python, never generated. (verified)

### Root Claude inventory and invocation edges

The source-derived root roster is 53 production and 78 test paths (131 total).
It is retired with the Codex roster below; an unmapped path blocks deletion.
(verified)

| Group | Current paths | Invocation edge that moves atomically |
| --- | --- | --- |
| Hook entries | `hooks/scripts/{agent_model_routing_nudge,agent_only_gate,check_confidence_labels,check_verify_loop,comment_citation_gate,crack_on_gate,crack_on_prose_gate,destructive_bash_gate,enforce_pr_workflow,inject_bootstrap,inject_context,loop_dispatch_guard,loop_stall_guard,loop_state_guard,no_edit_on_main,offload_push_guard,quality_feedback,remember_inject_cap_guard,test_gate,unregistered_loop_guard,verification_volume_ceiling,voice_announce,wiki_taxonomy_gate}.sh` | `hooks/hooks.json`: preserve event, matcher, timeout, stdin JSON, deny/allow, and fail-open/fail-closed contracts. |
| Hook helpers | `hooks/scripts/lib/{agentic_loop_path,discipline_common,graph_dispatch,graph_evidence,graph_evidence_bind,graph_evidence_revalidate,graph_executor,graph_readiness,loop_cost,loop_state_common}.sh` | Imports from hook entries, graph skills, and guards: retain Claude state-path, lock, evidence, and `Agent` handoff ownership. |
| Workflow, quality, sandbox, integrity | `scripts/{merge,post_evals,post_review,push}.sh`; `scripts/lib/{config,eval-artifact,git-common,post_evals_freeze,post_evals_smoke_freeze,post_evals_smoke_gate,post_evals_smoke_run,post_evals_structure,review-artifact}.sh`; `scripts/{quality/check,sandbox/render-settings,sandbox/sandbox-probe,sandbox/spawn-sandboxed-worker,integrity-gate/install,integrity-gate/integrity-gate-runner,integrity-gate/setup}.sh` | Root commands, skills, hook recognizers, `install.sh`, launchd/docs, and focused tests must name Python together. |
| Root tests | `hooks/scripts/tests/{agent_model_routing_nudge,agent_only_gate,agentic_loop_path,ceiling_note,check_confidence_labels,check_verify_loop,cli_antipatterns,codex_eval_authority,comment_citation_gate,config,crack_on_gate,crack_on_prose_gate,dashboard_agent,destructive_bash_gate,discipline_common,discriminate,docs_sync_routine,enforce_pr_workflow,eval-artifact,exec_bit_invariant,git-common,graph_contract,graph_dispatch,graph_dispatch_acceptance,graph_dispatch_complete,graph_dispatch_j12_s9,graph_evidence,graph_evidence_forgery,graph_evidence_mailbox,graph_evidence_notifications,graph_executor,graph_executor_concurrency,graph_executor_stale_check,graph_readiness,graph_two_unit_fanout,hooks_json_timeout_floor,init_yaml_validation,inject_bootstrap,inject_context,install_mode_sweep,install_routines,integrity_gate_install,loop_cost,loop_dispatch_guard,loop_stall_guard,loop_stall_guard_graph_complete,loop_state_guard,loop_state_guard_evals,merge,merge_evals_gate,merge_wiki_debt_gate,no_edit_on_main,offload_push_guard,post_evals,post_review,post_review_command,push_staging,quality_feedback,remember_inject_cap_guard,review-artifact,routine_runner_bin_targets,run_all,run_all_skip,sandbox_probe,sandbox_settings,seed_and_sweep_resilience,spawn_sandboxed_worker,stdin_bounded_read,stop_hook_human_escalation,test_gate,unregistered_loop_guard,verification_volume_ceiling,voice_announce,wiki_taxonomy_gate}.test.sh`; `hooks/scripts/tests/lib/claude_transcript_fixture.sh`; `scripts/{integrity-gate/tests/integrity-gate,integrity-gate/tests/setup,quality/tests/quality}.test.sh` | `run_all`, installer, graph, hook, quality, sandbox, and integrity composition: retain fixtures, negative controls, exits, and HOME/temp isolation. |

### Frozen inventory and invocation edges

The package-local inventory is 32 production and four test paths. With the 13
`packages/tests` paths listed below, Codex owns 49 retirement paths. A missing
mapping blocks deletion. (verified)

| Group | Current files | Invocation edge that must move with it |
| --- | --- | --- |
| Hook entry points | `hooks/scripts/{check_confidence_labels,comment_citation_gate,crack_on_gate,crack_on_prose_gate,destructive_bash_gate,graph_completion_guard,inject_bootstrap,inject_context,loop_dispatch_guard,no_edit_on_main,quality_feedback,test_gate,verification_volume_ceiling,wiki_taxonomy_gate}.sh` | Every entry is named by `hooks/hooks.json`; keep the same event, matcher, timeout, stdin JSON contract, and deny/allow output while changing its command to the `.py` entry point. |
| Hook helper | `hooks/scripts/lib/hook_common.sh` | Imported by all current hook entry points; replace it with one private Python module imported by those entry points, with no public shell-source contract. |
| Workflow CLI and helpers | `scripts/{push,merge,post_evals,post_review}.sh`, `scripts/lib/{config,eval-artifact,git-common,review-artifact}.sh` | `push`, `merge`, `post-evals`, and `post-review` skills resolve and execute these files; `merge` imports config, git-common, and post-evals; git-common imports both artifact helpers; post-evals imports eval-artifact; push imports git-common. Move those imports to Python modules and update every skill command/reference atomically. |
| Dashboard launchers | `skills/dashboard/runner/bin/{dashboard-server,seed-and-sweep,sweeper}.sh`, `skills/dashboard/scripts/{run-builder,start-dashboard,stop-dashboard}.sh` | Dashboard skill invokes start/stop; runner binaries start Node entry points and set `CODERAILS_BUILDER_WRAPPER`; the dashboard app discovers/spawns `run-builder.sh`; runner/app tests assert these paths. Rename the discovery constant, environment value, identity marker, tests, and documentation to `.py` in the same batch. |
| Workflow-audit production | `skills/workflow-audit/scripts/{scan_transcripts,cluster_ngrams,write_queue_entry}.sh` | `workflow-audit/SKILL.md` pipes scan to cluster and pipes judge output to queue writer. Preserve JSONL and privacy filtering, but invoke the three Python entry points directly. |
| Workflow-audit test runners | `skills/workflow-audit/scripts/tests/{cluster_ngrams,e2e,scan_transcripts,write_queue_entry}.test.sh` | Each directly runs one or more workflow-audit production scripts. Convert them to Python tests before deleting the production shell files; retain unit and scan-to-cluster integration coverage. |

The Codex package test surface outside the package directory is also retired:
`packages/tests/{codex_frozen_evals,codex_graph_evidence_shapes,codex_graph_runtime_adversarial,codex_hooks,codex_installer,codex_native_package,codex_shell_retirement_contracts,provider_graph_adversarial,provider_graph_final_adversarial,provider_graph_lifecycle_adversarial,provider_graph_parity,stop_hook_human_escalation}.test.sh`
and `packages/tests/lib/codex_transcript_fixture.sh` become Python tests/module
in M2X. (verified)

### Ordered migration batches and gates

**M0 — freeze contracts and baseline (integration worktree).** Add a failing
two-provider no-`.sh` inventory check, map every path to stream/exit/environment
coverage, inventory the known 67 non-Python quality findings and five stale
`provider_graph_parity` fixtures, and do not repair shell lint that deletion
removes. (verified)

**M1 — semantic prerequisites (integration worktree).** Complete Phases 0–2:
quality baseline, frozen corpus, and maintained core. (verified)

**M2C/M2X — provider migration (parallel Claude-only/Codex-only worktrees).**
M2C converts all 131 root paths while preserving Claude locks, evidence, hooks,
and `Agent`; M2X converts all 49 Codex paths while preserving Codex hooks,
evidence, and `spawn_agent`. Move hook configuration, skills, source/imports,
installer references, TypeScript discovery, and tests atomically with each
entry point. (verified)

**M3 — integration (integration worktree; after M2C/M2X).** Complete Phases
4–5, materialize the semantic core, remove every `.sh`, and run cross-provider
parity and native acceptance. **M4 — final gates (integration worktree; after
M3).** The strict non-bypassed quality gate has zero unresolved findings,
including all 67; all five parity fixtures pass with their provider-local
raw-evidence purpose; no executable `.sh` reference remains in config, skills,
source, tests, installers, or docs. (verified)

| Phase | Owner/worktree | Prerequisite | Deliverable |
| --- | --- | --- | --- |
| 0. Python quality baseline | Codex, integration worktree | none | Enforced tools and zero existing Python violations |
| 1. Freeze fixtures | Codex, integration worktree | Phase 0 | Frozen provider-neutral semantic corpus and runner |
| 2. Extract core | Codex, integration worktree | Phases 0–1 | `packages/graph-semantics/` pure Python core |
| 3A. Claude adapter | Claude headless, Claude-only worktree | Phases 0–2 | Python adapter behind existing Claude Bash/hook boundaries |
| 3B. Codex adapter | Codex, Codex-only worktree | Phases 0–2 | `graph.py` becomes an I/O adapter over the core |
| 4. Materialize and parity | Codex, integration worktree | 3A and 3B | Installer generation and cross-adapter corpus parity |
| 5. Native acceptance | Both providers, integration worktree | Phase 4 | Provider-native acceptance evidence |

Phases 0, 1, 2, 4, and 5 are serial gates. Only 3A and 3B run in parallel. (verified)

## Phase 0 — enforce the Python quality baseline

1. Inventory every existing Python file and run the selected tools before
   changing graph semantics. Fix every violation; do not add exemptions.
2. Add authoritative `pyproject.toml` configuration for Ruff, Black, Pyright,
   and mypy. Enforce PEP 8, PEP 20 review discipline, PEP 257 Google-style
   public docstrings, strict typing, import order, and the project’s existing
   no-commented-code rule.
3. Modify the existing strict quality entry point, not a parallel workflow, so
   missing Python tools fail strict mode and every later commit validates all
   Python files touched by the migration.
4. Add focused quality-gate tests: a bad formatter/linter/type/docstring case
   must fail; a compliant Google-docstring fixture must pass.

**Phase check:** the strict quality command passes for every Python file;
Ruff, Black, Pyright, and mypy all pass; the negative controls fail; no Python
file is listed in a LOC or function-size exception solely to avoid remediation.

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
   - Inventory each retired Claude and Codex semantic behaviour and map it to
     one frozen fixture or provider-local test before its old implementation is
     deleted; an unmapped behaviour blocks retirement. (verified)
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
   Delete the corresponding retired semantic implementation after the corpus
   proves equivalent behaviour; do not leave a fallback branch. (verified)
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
   Confirm the capability inventory is complete and every retired path is
   removed rather than grandfathered. (verified)

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
