---
name: provider-python-migration-remote-handoff
description: Continue the incomplete two-provider Python clean cutover from the pushed feature branch on another computer.
type: project
---

# Provider Python migration remote handoff

> Supersession note (2026-09-21): This is a historical handoff for work on a remote machine. Its branch, graph path, unfinished work, and shell test commands apply only to that checkpoint. Do not continue or change the historical graph. Examine the current checkout and the graph data for the session that owns it. The current cutover uses Python entrypoints and schema 3 only.

## Goal

Complete the approved cutover. Use Python for all Coderails-owned Claude and Codex runtime paths. Use only schema v3. Keep each provider's native dispatch and its records. Show that strict quality, parity, and live native operation meet the test criteria. Do not publish, open a PR, or merge without new authorization.

## Decisions and constraints

- Historical graph `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a061b6-79e2-7bf0-8935-57399e7d52bc/progress.json` is a closed record.
- Multiple successor graphs hard-stopped. Native task identifiers are global to a session and activation gates had to get explicit approvals. Keep those graphs closed. Start a new graph with stable work-unit IDs that no graph in the session uses.
- `graph_evidence.py` accepts this live native chain: `spawn_agent` function call, `SubAgentActivity`, and child `task_complete`. It also accepts legacy records and keeps fail-closed checks.
- User explicitly approved activation/deletion for these root Claude hooks: agent-only, comment-citation, no-edit-on-main, offload-push, quality-feedback, verification-volume, crack-on, crack-on-prose.
- Keep all uncommitted changes in the integration worktree. Do not use `git reset`, add files to the index broadly, force push, or bypass quality checks.

## Completed this handoff

- Repaired native Codex graph record binding and added tests for adversarial inputs.
- Root Claude Python cutovers include `agent_model_routing_nudge`, `inject_bootstrap`, `inject_context`, and `graph_readiness`. They also include `agent_only_gate`, `comment_citation_gate`, `no_edit_on_main`, `offload_push_guard`, `quality_feedback`, `verification_volume_ceiling`, `crack_on_gate`, and `crack_on_prose_gate`.
- The targeted tests for the activated hooks succeeded. The full `hooks/scripts/tests/run_all.sh` run finished without a recorded exit status. The verification-volume ceiling blocked the replacement run. Do not report that the full suite succeeded.

## Key files

- `project_provider-python-migration-clean-cutover.md`: approved outcome and boundaries.
- `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md` gives the migration steps in sequence.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` links native records to the graph.
- `hooks/hooks.json`: root hook registration migration surface.
- `hooks/scripts/`: remaining Claude Bash retirement inventory.
- `packages/codex/` and `packages/tests/`: remaining Codex and package test retirement inventory.

## Next steps

1. Check the branch and worktree status again. Check the current `.sh` inventory and all changes in the index and worktree.
2. Start a new schema-v3 graph with frozen loop evals and `U3[n]` IDs that no graph in the session uses.
3. Finish root Claude stateful hook entries, safeguards, PR gates, and hook libraries. Finish workflow, quality, sandbox, and integrity paths and all related tests.
4. Finish Codex hook, workflow/dashboard/workflow-audit, and package-test migrations.
5. Remove remaining v2 paths and all links to executable `.sh` files. Run strict quality checks and five parity fixtures. Test that each provider works through its native path.
