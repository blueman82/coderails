---
name: provider-python-migration-remote-handoff
description: Continue the incomplete two-provider Python clean cutover from the pushed feature branch on another computer.
type: project
---

# Provider Python migration remote handoff

## Goal

Complete the approved clean cutover: Python for all Coderails-owned Claude and Codex runtime paths, schema v3 only, provider-native dispatch/evidence retained, strict quality/parity/native acceptance green. Do not publish, create a PR, or merge without a new authorization.

## Decisions and constraints

- Historical graph `/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a061b6-79e2-7bf0-8935-57399e7d52bc/progress.json` is closed historical evidence.
- Multiple successor graphs hard-stopped because native task identifiers are global to a session and activation gates needed explicit approvals. Do not resume them; start a fresh graph with unused stable work-unit IDs.
- `graph_evidence.py` now accepts the live native `spawn_agent` function-call + `SubAgentActivity` + child `task_complete` evidence chain while retaining legacy evidence and fail-closed checks.
- User explicitly approved activation/deletion for these root Claude hooks: agent-only, comment-citation, no-edit-on-main, offload-push, quality-feedback, verification-volume, crack-on, crack-on-prose.
- Preserve all dirty integration-worktree changes; no reset, broad staging, force push, or quality bypass.

## Completed this handoff

- Native Codex graph evidence binding repair with focused adversarial coverage.
- Root Claude Python cutovers activated for: `agent_model_routing_nudge`, `inject_bootstrap`, `inject_context`, `graph_readiness`, `agent_only_gate`, `comment_citation_gate`, `no_edit_on_main`, `offload_push_guard`, `quality_feedback`, `verification_volume_ceiling`, `crack_on_gate`, and `crack_on_prose_gate`.
- Focused tests for the activated hooks passed. A full `hooks/scripts/tests/run_all.sh` process completed but its exit status was not captured; a replacement run was blocked by the verification-volume ceiling, so do not report it green.

## Key files

- `project_provider-python-migration-clean-cutover.md`: approved outcome and boundaries.
- `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md`: ordered migration plan.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py`: repaired native evidence binding.
- `hooks/hooks.json`: root hook registration migration surface.
- `hooks/scripts/`: remaining Claude Bash retirement inventory.
- `packages/codex/` and `packages/tests/`: remaining Codex and package test retirement inventory.

## Next steps

1. Recheck branch, worktree status, current `.sh` inventory, and all staged/unstaged changes.
2. Start a fresh schema-v3 graph with new unused `U3[n]` IDs and frozen loop evals.
3. Finish root Claude stateful hook entries, security/PR gates, hook libraries, workflow/quality/sandbox/integrity paths, and their tests.
4. Finish Codex hook, workflow/dashboard/workflow-audit, and package-test migrations.
5. Remove residual v2 routes and all executable `.sh` references, then run strict quality, five parity fixtures, and provider-native acceptance.
