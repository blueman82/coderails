# Provider graph-alignment implementation plan

> Implementation update (2026-09-21). The shell lists and earlier commands below are the frozen migration baseline. The clean-break change replaces the instructions to run or keep these paths.

> The current installer uses `install.py` and `scripts/installer/files.py`. Current entry points and tests use Python.
> See `hooks/scripts/tests/run_all.py`, `packages/tests/test_graph_semantics_fixtures.py`, and `packages/tests/test_provider_graph_parity.py`.

> For current commands, see [the component guide](../../REFERENCE.md) and [installation guide](../../../INSTALLATION.md).
> The current code has no shell wrapper and no reader for schema versions 1 or 2.

## Purpose and fixed boundaries

Use the approved schema-v3 contract from `docs/superpowers/specs/2026-09-02-provider-graph-alignment-design.md`. Do not add a shared installed runtime.
Keep one maintained Python source in `packages/graph-semantics/`. Use `install.sh` to copy it into the Claude and Codex bundles, which install independently. (verified)

The core owns only pure validation and changes to the graph.
Each provider adapter owns its paths, locks, atomic writes, native dispatch, transcript parsing, raw provider records, hooks, and gates for loop end. (verified)

### Protected files and non-goals

- Keep the approved untracked design document. Do not edit it during implementation. (verified)
- Do not add a scheduler, daemon, shared worker launcher, or provider router. Do not add a shared transcript parser or store for raw provider records. (verified)
- Do not change Claude `Agent` dispatch or Codex `spawn_agent` dispatch. (verified)

- Do not map `work_units` to `graph.nodes`. Do not migrate v1/v2 files or write two versions. Use one schema version in each wave. (verified)
- Keep all provider functions and safety gates. Remove the prior semantic path in the same change. Do not keep a legacy fallback, compatibility shim, dual reader, or dual writer. (verified)
- Do not edit the generated bundle copies by hand. The paths are `skills/agentic-loop/scripts/graph_semantics.py` and `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`. (verified)
- Do not change Factory code or behaviour. (verified)

## Worktree ownership and order

## Two-provider Python clean-break amendment

This change applies to all Coderails shell paths for Claude and Codex listed below. It replaces each earlier instruction to keep a `.sh` path.
Use only Python for the provider-owned code. Keep no legacy Bash wrapper, compatibility fallback, dual reader or writer, or exemptions for prior paths.
Claude `Agent` and Codex `multi_agent_v1__spawn_agent` dispatch stay native to their providers. (verified)

### End state and constraints

`find hooks/scripts scripts packages/codex packages/tests -type f -name '*.sh'` must find no Coderails shell path. This includes launchers, helpers, test shims, compatibility wrappers, and prior paths.
Each batch must keep the CLI, stdin, stdout, stderr, exit status, timeout, environment, file system effects, and behaviour on error.

Use Python standard library modules first. These include `argparse`, `json`, `pathlib`, `subprocess`, `tempfile`, `fcntl`, and `unittest`.
Keep external commands only if the existing contract requires them. Add no runtime package.

Entry points use `#!/usr/bin/env python3`. Callers name the `.py` paths.
The installer copies `packages/graph-semantics/graph_semantics.py` into the two generated paths.
Keep the new Python scripts as source files. (verified)

### Root Claude inventory and invocation edges

The root inventory comes from source. It has 53 production and 78 test paths (131 total).
Retire it with the Codex inventory below. Remove a path only after you map it to its replacement. (verified)

| Group | Current paths | Changes in the same batch |
| --- | --- | --- |
| Hook entries | `hooks/scripts/{agent_model_routing_nudge,agent_only_gate,check_confidence_labels,check_verify_loop,comment_citation_gate,crack_on_gate,crack_on_prose_gate,destructive_bash_gate,enforce_pr_workflow,inject_bootstrap,inject_context,loop_dispatch_guard,loop_stall_guard,loop_state_guard,no_edit_on_main,offload_push_guard,quality_feedback,remember_inject_cap_guard,test_gate,unregistered_loop_guard,verification_volume_ceiling,voice_announce,wiki_taxonomy_gate}.sh` | Update `hooks/hooks.json`. Keep the hook trigger, matcher, timeout, stdin JSON, deny/allow, and behaviour if a check gives an error. |
| Hook helpers | `hooks/scripts/lib/{agentic_loop_path,discipline_common,graph_dispatch,graph_evidence,graph_evidence_bind,graph_evidence_revalidate,graph_executor,graph_readiness,loop_cost,loop_state_common}.sh` | Keep Claude in control of the paths, locks, worker records, and `Agent` handoff. Update imports from hooks, graph skills, and guards. |
| Workflow, quality, sandbox, integrity | `scripts/{merge,post_evals,post_review,push}.sh`, `scripts/lib/{config,eval-artifact,git-common,post_evals_freeze,post_evals_smoke_freeze,post_evals_smoke_gate,post_evals_smoke_run,post_evals_structure,review-artifact}.sh`, `scripts/{quality/check,sandbox/render-settings,sandbox/sandbox-probe,sandbox/spawn-sandboxed-worker,integrity-gate/install,integrity-gate/integrity-gate-runner,integrity-gate/setup}.sh` | Update the root commands, skills, hook recognizers, `install.sh`, launchd, docs, and tests together. |
| Root tests | `hooks/scripts/tests/{agent_model_routing_nudge,agent_only_gate,agentic_loop_path,ceiling_note,check_confidence_labels,check_verify_loop,cli_antipatterns,codex_eval_authority,comment_citation_gate,config,crack_on_gate,crack_on_prose_gate,dashboard_agent,destructive_bash_gate,discipline_common,discriminate,docs_sync_routine,enforce_pr_workflow,eval-artifact,exec_bit_invariant,git-common,graph_contract,graph_dispatch,graph_dispatch_acceptance,graph_dispatch_complete,graph_dispatch_j12_s9,graph_evidence,graph_evidence_forgery,graph_evidence_mailbox,graph_evidence_notifications,graph_executor,graph_executor_concurrency,graph_executor_stale_check,graph_readiness,graph_two_unit_fanout,hooks_json_timeout_floor,init_yaml_validation,inject_bootstrap,inject_context,install_mode_sweep,install_routines,integrity_gate_install,loop_cost,loop_dispatch_guard,loop_stall_guard,loop_stall_guard_graph_complete,loop_state_guard,loop_state_guard_evals,merge,merge_evals_gate,merge_wiki_debt_gate,no_edit_on_main,offload_push_guard,post_evals,post_review,post_review_command,push_staging,quality_feedback,remember_inject_cap_guard,review-artifact,routine_runner_bin_targets,run_all,run_all_skip,sandbox_probe,sandbox_settings,seed_and_sweep_resilience,spawn_sandboxed_worker,stdin_bounded_read,stop_hook_human_escalation,test_gate,unregistered_loop_guard,verification_volume_ceiling,voice_announce,wiki_taxonomy_gate}.test.sh`, `hooks/scripts/tests/lib/claude_transcript_fixture.sh`, `scripts/{integrity-gate/tests/integrity-gate,integrity-gate/tests/setup,quality/tests/quality}.test.sh` | Update `run_all`, the installer, graph, hooks, quality, sandbox, and integrity. Keep fixtures, negative controls, exit codes, and separation of HOME and temporary files. |

### Frozen inventory and invocation edges

The Codex package has 32 production and four test paths. The 13 paths in `packages/tests` below give a total of 49 paths to retire. Remove a path only after you map it to its replacement. (verified)

| Group | Current files | Changes in the same batch |
| --- | --- | --- |
| Hook entry points | `hooks/scripts/{check_confidence_labels,comment_citation_gate,crack_on_gate,crack_on_prose_gate,destructive_bash_gate,graph_completion_guard,inject_bootstrap,inject_context,loop_dispatch_guard,no_edit_on_main,quality_feedback,test_gate,verification_volume_ceiling,wiki_taxonomy_gate}.sh` | Update all commands in `hooks/hooks.json` to use the `.py` paths. Keep the hook trigger, matcher, timeout, stdin JSON, and deny/allow output. |
| Hook helper | `hooks/scripts/lib/hook_common.sh` | Use one private Python module for imports from all current hook entry points. Keep no public shell source interface. |
| Workflow CLI and helpers | `scripts/{push,merge,post_evals,post_review}.sh`, `scripts/lib/{config,eval-artifact,git-common,review-artifact}.sh` | The `push`, `merge`, `post-evals`, and `post-review` skills find and run these files. The `merge` script imports config, git-common, and post-evals. The git-common script imports the two artifact helpers. The post-evals script imports eval-artifact. The push script imports git-common. Move the imports to Python and update all skill commands and file pointers in the same batch. |
| Dashboard launchers | `skills/dashboard/runner/bin/{dashboard-server,seed-and-sweep,sweeper}.sh`, `skills/dashboard/scripts/{run-builder,start-dashboard,stop-dashboard}.sh` | The dashboard skill calls start and stop. The runner binaries start Node and set `CODERAILS_BUILDER_WRAPPER`. The app finds and starts `run-builder.sh`. Tests for the runner and app check those paths. Update the discovery constant, environment value, identity marker, tests, and docs to `.py` in the same batch. |
| Workflow-audit production | `skills/workflow-audit/scripts/{scan_transcripts,cluster_ngrams,write_queue_entry}.sh` | `workflow-audit/SKILL.md` pipes scan output to cluster and judge output to the queue writer. Keep JSONL and privacy filters. Run the three Python entry points directly. |
| Workflow-audit test runners | `skills/workflow-audit/scripts/tests/{cluster_ngrams,e2e,scan_transcripts,write_queue_entry}.test.sh` | Each runner calls one or more production scripts directly. Change the runners to Python before you remove the production shell files. Keep unit tests and scan-to-cluster integration tests. |

In M2X, change these external Codex tests and the fixture helper to Python. (verified)

`packages/tests/{codex_frozen_evals,codex_graph_evidence_shapes,codex_graph_runtime_adversarial,codex_hooks,codex_installer,codex_native_package,codex_shell_retirement_contracts,provider_graph_adversarial,provider_graph_final_adversarial,provider_graph_lifecycle_adversarial,provider_graph_parity,stop_hook_human_escalation}.test.sh`
and `packages/tests/lib/codex_transcript_fixture.sh`.

### Ordered migration batches and gates

**M0 — freeze contracts and baseline (integration worktree).** Add a two-provider check that rejects all `.sh` paths in scope. Map each path to tests of streams, exits, and environment. List the 67 non-Python quality issues and the five stale `provider_graph_parity` fixtures. Do not correct shell lint in files due for deletion. (verified)

**M1 — semantic prerequisites (integration worktree).** Complete Phases 0–2. This covers the quality baseline, frozen fixtures, and maintained core. (verified)

**M2C/M2X — provider migration (parallel Claude-only/Codex-only worktrees).**
M2C converts all 131 root paths and keeps Claude locks, worker records, hooks, and `Agent`. M2X converts all 49 Codex paths and keeps Codex hooks, worker records, and `spawn_agent`.
Update hook configuration, skills, source and imports, installer paths, TypeScript discovery, and tests in the same batch as each entry point. (verified)

**M3 — integration (integration worktree, after M2C/M2X).** Complete Phases 4–5, make the two core copies and remove all `.sh` files. Run parity tests and a native test to accept the change for each provider.

**M4 — last gates (integration worktree, after M3).** Run the strict quality gate with no bypass. It must report zero open issues. This covers the 67 from M0. All five parity fixtures must give success for their provider-local raw-evidence checks. Remove executable pointers to `.sh` files from config, skills, source, tests, installers, or docs. (verified)

| Phase | Owner/worktree | Prerequisite | Deliverable |
| --- | --- | --- | --- |
| 0. Python quality baseline | Codex, integration worktree | None | Mandatory tools and zero existing Python violations |
| 1. Freeze fixtures | Codex, integration worktree | Phase 0 | Frozen provider-neutral fixtures and runner |
| 2. Move logic to the core | Codex, integration worktree | Phases 0–1 | `packages/graph-semantics/` pure Python core |
| 3A. Claude adapter | Claude headless, Claude-only worktree | Phases 0–2 | Python adapter behind existing Claude Bash/hook boundaries |
| 3B. Codex adapter | Codex, Codex-only worktree | Phases 0–2 | `graph.py` becomes the I/O adapter for the core |
| 4. Copy the core and check parity | Codex, integration worktree | 3A and 3B | Installer copies and parity across adapters |
| 5. Native tests | Claude and Codex, integration worktree | Phase 4 | Results of the native test loops |

Do Phases 0, 1, 2, 4, and 5 in sequence. Only 3A and 3B run in parallel. (verified)

## Phase 0 — enforce the Python quality baseline

1. List all existing Python files. Run the selected tools before changes to the graph. Correct all violations. Add no exemptions.
2. Put the authoritative configuration for Ruff, Black, Pyright, and mypy in `pyproject.toml`. Apply PEP 8, PEP 20 in code inspection, and PEP 257 Google-style public docstrings. Apply strict typing, import sequence, and the existing ban on commented-out code.

3. Change the existing strict quality command. Add no parallel workflow. Strict mode must reject a run without all Python tools. Each subsequent commit must validate all Python files in the migration.
4. Add focused quality-gate tests. Each example with a formatter, linter, type, or docstring error must give an error. A fixture with a correct Google-style docstring must give success.

**Phase check:** Run the strict quality command on all Python files. Ruff, Black, Pyright, and mypy must give success. The negative controls must give errors. Do not use the LOC or function-size allowlists to skip corrections.

## Phase 1 — freeze the canonical fixture corpus

1. Add `packages/graph-semantics/fixtures/`. Keep each canonical input, operation input, expected canonical output, or expected error as a deterministic JSON fixture. Add `packages/tests/graph_semantics_fixtures.test.sh` as the only runner for this set. (inferred)
2. Freeze the fixtures before you move the code into the core. Test the full schema-v3 contract.
   - Reject schema versions 1 and 2. Check root revision `1`, the full grammar for stable IDs, and the registry of human labels.
   - Check all nine permitted result and status tokens. Reject `failed` in new graph data on disk.
   - Check correct and incorrect topology, self-edges, cycles, and a mismatch between a join key and `join.id`.
   - Check the node sequence from `ready`, fan-out, and release of a join only after all its inputs.
   - Check that `begin_wave` sets `active_wave.wave_id`, marks only the specified nodes, and rejects a second active wave.

   - Check that `record_wave` rejects missing or stale results. It also rejects results from an incorrect wave or for nodes that the wave does not contain. Input stays unchanged on error. The core changes `failed` to `pending` for a retry or `hard-stop` when no retry remains.
   - Check `stale_check` validation, `respawn_stale` generation and intent, no changes to topology, no automatic dispatch, and `hard_stop` preconditions.
   - Check the sequence of `can_complete` blockers. Check v3 `work_units` independently of the graph. A missing field, `null`, or `{}` succeeds. Entries with `done` or `dropped` with a `dropped_reason` succeed.

   - Check that arrays, malformed entries, unknown statuses, and `dropped` without a `dropped_reason` block the end of the loop. (verified)
   - List each Claude and Codex semantic behaviour due for retirement. Map it to a frozen fixture or provider-local test. If it has no match, keep the prior path until there is a match. (verified)

3. Keep a negative control with an incorrect active-wave result set. Check that the runner gives an error and the source data stays byte for byte the same. (verified)
4. Keep the purpose of `packages/tests/provider_graph_parity.test.sh`. It tests provider-local raw provider records and transcripts. Use the canonical fixture runner for semantics. (verified)

**Phase check:** `bash packages/tests/graph_semantics_fixtures.test.sh` and `git diff --check` must give success. The negative control must give an error. (inferred)

## Phase 2 — implement the pure maintained Python core

1. Add `packages/graph-semantics/graph_semantics.py` and a small `__init__.py` if necessary. Use only the Python standard library. Accept all graph data and the operation input. Give the complete proposed data or a deterministic semantic error. Do no file I/O, locking, subprocess calls, provider imports, transcript lookup, or worker-record lookup. (verified)

2. Add the approved API to the module. Use `validate`, `ready`, `begin_wave`, `record_wave`, `respawn_stale`, `hard_stop`, `inspect`, and `can_complete`. Keep all canonical changes in these functions. (verified)
3. Move the shared state-machine behaviour from these Codex `packages/codex/skills/agentic-loop/scripts/graph.py` functions into the pure API. Move `_validate_state`, `_dependencies`, `_release_joins`, `_ready`, and `_results`. Also move `_begin_wave`, `_record_wave`, `_inspect`, and `_validate_completion`. Do not move `_load`, `_write`, `_locked`, `_authorize_dispatch`, or anything in `graph_evidence.py`. (verified)

   Remove the prior semantic code after the fixtures show equivalent behaviour. Keep no fallback branch. (verified)

4. Use deterministic error text and codes in the core. Check for a byte-for-byte match in the fixture runner. Check that the input data stays unchanged when the core rejects it. The core copies the input before it makes changes, so it cannot change part of an invalid input. (inferred)
5. Add a Python test entry point in `packages/graph-semantics/tests/` only for checks the frozen fixture runner does not include. Use the frozen fixtures as the source of truth. (inferred)

**Phase check:** Run the fixture runner against the core. Run `python3 -m py_compile packages/graph-semantics/graph_semantics.py`. Use `rg` to check that the core imports no provider-local module. (inferred)

## Phase 3A — migrate the Claude semantic adapter (parallel)

### Ownership

Run Claude headless only in its own worktree. Codex must not edit those files at the same time.
Keep Claude-native Bash locks, hook interfaces, `Agent` handoff, progress-path lookup, and raw-evidence binding. (verified)

### Exact changes

1. Replace the validation, readiness, and wave change logic in `hooks/scripts/lib/graph_readiness.sh`, `hooks/scripts/lib/graph_executor.sh`, and `hooks/scripts/lib/graph_dispatch.sh`. Add thin calls to the generated `skills/agentic-loop/scripts/graph_semantics.py` CLI or module.
   Keep each public shell function name and calling contract. These include `graph_executor_graph_valid`, `graph_executor_ready_nodes`, `graph_executor_apply_wave`, and the `graph_dispatch_*` functions that skills and hook guards use. (verified)

2. Keep `hooks/scripts/lib/loop_state_common.sh` as the only owner of Claude paths, locks, and atomic writes. With the lock active, read the full file and run one core operation. Check the result and replace the file atomically. (verified)
3. Keep Claude-only code for worker records and dispatch. This includes `hooks/scripts/lib/graph_evidence.sh` if dispatch uses it, `hooks/scripts/loop_dispatch_guard.sh`, and the `Agent` payload contract.
   Normalize only the semantic pointer to the worker record you give to `record_wave`. Keep transcript parsing out of the core. (verified)

4. Change `skills/agentic-loop/loop-state.md`, `skills/agentic-loop/execution-graph.md`, and `skills/agentic-loop/SKILL.md` only where the command and data contract changes. Give the rules for schema v3, `wave_id`, stable IDs, stale checks and respawn, and strict v3 `work_units`. Keep other workflow prose. (inferred)
5. Update the existing Claude tests. Add no parallel replacements.
   Use `hooks/scripts/tests/graph_contract.test.sh`, `graph_readiness.test.sh`, `graph_executor.test.sh`, `graph_executor_stale_check.test.sh`, `graph_dispatch.test.sh`, `graph_dispatch_acceptance.test.sh`, `graph_dispatch_complete.test.sh`, `graph_two_unit_fanout.test.sh`, and `loop_stall_guard_graph_complete.test.sh`.
   Keep the checks for provider-native locks, worker records, and hooks. (verified)

### Headless Claude execution

Run only one Claude task at a time from the Claude-only worktree. Set a limit for each task.

```zsh
claude --model sonnet -p "$PROMPT" --output-format stream-json --verbose --no-session-persistence \
  | jq -r 'if .type == "assistant" then .message.content[]? | select(.type == "text") | .text elif .type == "result" then .result else empty end'
```

In the prompt, list the Phase-3A files. Specify no Factory or Codex edits. Specify `apply_patch` and native Claude test output.
Keep the transcript JSON only to find the cause of problems. Report each text or result output one time. (verified)

**Phase check:** Run `bash hooks/scripts/tests/graph_contract.test.sh`, `bash hooks/scripts/tests/graph_readiness.test.sh`, `bash hooks/scripts/tests/graph_executor.test.sh`, `bash hooks/scripts/tests/graph_executor_stale_check.test.sh`, and the dispatch and loop-end tests above from the Claude worktree. All must give success. (inferred)

## Phase 3B — migrate the Codex semantic adapter (parallel)

1. Keep `packages/codex/skills/agentic-loop/scripts/graph.py` as the native Codex CLI and I/O adapter.
   Keep `_load`, `_write`, `_locked`, the CLI parser, `main`, `transcript_cursor`, `bind_worker_evidence`, `validate_worker_evidence`, `validate_evals`, and `validate_completion_evidence`.
   Replace the duplicate semantic functions with calls to the generated `graph_semantics.py`. (verified)

2. Keep `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` and `graph_identity.py` in Codex for worker records and task names.
   Give the task its provider-native identity only after the core runs `begin_wave`. For a stale respawn, do this only in the subsequent dispatch wave. (verified)
3. Add `respawn-stale` and `hard-stop` to the `graph.py` CLI. Keep the file lock and atomic replacement in the adapter.
   Update only `packages/codex/skills/agentic-loop/SKILL.md`, `packages/codex/hooks/scripts/graph_completion_guard.sh`, and `packages/codex/hooks/scripts/loop_dispatch_guard.sh` where the new schema or command contract requires it. (inferred)

4. Change `_complete` and `_verify_completion` to use core `can_complete` to check the canonical graph first. Then check Codex v3 `work_units` independently. Also run the existing native worker record, eval, proof, and retro checks. Do not connect `work_units` to nodes. (verified)
5. Update existing Codex tests. Use `packages/tests/codex_graph_runtime_adversarial.test.sh`, `packages/tests/codex_graph_evidence_shapes.test.sh`, `packages/tests/provider_graph_lifecycle_adversarial.test.sh`, and `packages/tests/provider_graph_final_adversarial.test.sh`.
   Add only tests for the v3 adapter boundary and for retention of native worker records. (inferred)

**Phase check:** Run those four tests and `python3 -m py_compile packages/codex/skills/agentic-loop/scripts/graph.py` from the Codex worktree. (inferred)

## Phase 4 — installer materialization and semantic parity

1. Change only the existing `install.sh` flow. Copy `packages/graph-semantics/graph_semantics.py` only to these two paths.
   - `skills/agentic-loop/scripts/graph_semantics.py`
   - `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`

   Do this before the installer starts installation for Claude or Codex. Use the existing Bash 3.2 style and atomic-copy patterns if available. Add no packaging framework. (verified)

2. Add a small helper to `install.sh`. Make parent paths, copy the maintained source, and run `cmp -s` for each copy. If a copy differs, stop before plugin installation and give an error. Only this helper can write the generated copies. (inferred)

3. Extend `packages/tests/codex_installer.test.sh` and the root installer tests. Use `hooks/scripts/tests/install_routines.test.sh`, `hooks/scripts/tests/install_mode_sweep.test.sh`, or the two tests if the existing HOME sandbox applies.
   Show that each install mode produce copies that match the source byte for byte. Check that installation leaves the source unchanged. Keep the fresh-`$HOME`, executable-mode, and macOS Bash 3.2 checks. (verified)

4. Change the schema-v2 assumptions in `packages/tests/provider_graph_parity.test.sh` only where necessary for v3. Keep its raw-evidence fixture setup and native guard checks.
   Add `packages/tests/graph_semantics_adapter_parity.test.sh` as a new test. Run all frozen fixtures through the generated Claude and Codex adapters. Remove only the envelope and worker record fields that the provider owns. Compare canonical graph output and semantic errors byte for byte. Do not simulate native dispatch or inspect raw provider records. (inferred)

5. Find where the existing quality or CI command runs `hooks/scripts/tests/run_all.sh` and the package tests. Add the check that the copies match there. Do not add a CI workflow. (inferred)

**Phase check:** Run `cmp -s` from the maintained source to each copy. Run the installer sandbox tests and the two parity tests. Run the active-wave negative control and check that it gives an error. (verified)

## Phase 5 — native acceptance and integration review

1. In the integration worktree, run all focused tests from Phases 1, 3A, 3B, and 4. Then run the standard root and Codex test entry points from their existing runners. Record each command, exit status, and revision. (inferred)

2. Run a Claude-native test loop with the generated Claude bundle. Examine the graph and begin a wave. Hand off to native `Agent` dispatch. Collect only the results for that wave, record them, and complete the loop. Test fan-out and joins, retry exhaustion, stale check and explicit respawn, and the strict `work_units` gate for loop end. Do not invoke Codex in this loop. (inferred)

3. Run the same test loop with the generated Codex bundle and native `spawn_agent` handoff. Before the loop ends, check the Codex transcript records again. Do not invoke Claude in this loop. (verified)

4. Do two inspections independently. Claude headless checks the Codex adapter and integration changes. Codex checks the Claude adapter and integration changes. Each checks only current-worktree diffs against the frozen fixtures and the protected boundaries. (inferred)

5. Accept the change only after all of these checks give success.
   - One maintained source and two generated copies that match it.
   - v3 fixtures pass for the core and the two adapters.
   - The provider-local raw-evidence tests pass.
   - No v1 or v2 conversion.
   - No shared installed runtime, scheduler, dispatch path, or worker-record path.
   - Each native test loop gives success. (verified)

   Check that the inventory of functions is complete. Remove all paths due for retirement, with no exemptions. (verified)

## Implementation handoff checklist

- Make and freeze task evals from this plan before Phase 1 implementation. (verified)
- Start one native agentic-loop graph after you freeze the evals. The orchestrator alone records the durable plan and waves. (verified)

- The integration worktree owner handles merges for fixtures, core, and installer. Keep the provider worktrees isolated until Phase 4. (inferred)
- Stop before commit, push, or Factory work unless you have authority for that step. (verified)

## Did Not Verify

- The point where CI combines package and root tests. Find it in Phase 4 before you add the required check for both copies. (verified)
- If every Claude graph helper has a public caller outside the focused tests above. In Phase 3A, search for callers before you delete any semantic branch. (verified)
