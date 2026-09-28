# Memory Index

The Coderails implementation handoffs below are historical checkpoints, not current task authorization or live progress. The Python/schema-3 cutover supersedes their old paths and resume instructions; use the current owned session graph, [implementation plan](../../docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md), and [component reference](../../docs/REFERENCE.md). The standalone Factory record remains a separate project.

- `project-stop-hook-human-escalation.md` — historical handoff to replace repeated raw Claude/Codex loop-stop prompts with one clear, deduplicated human escalation.

- `project_standalone-factory-recovery.md` — standalone Factory recovery: dashboard boundary, current failed evals, and first repair steps.

- `project_coderails-graph-engineering-walkthrough.md` — historical verified baseline and example-first teaching contract for a complete Claude and Codex graph-engineering walkthrough after PRs #458-#460.
- `project_codex-evidence-shape-normalization.md` — historical Codex-only handoff for closing the remaining encoded-evidence bypass and requiring an independent exact-head tampering audit before merge.
- `project_codex-graph-evidence-binding.md` — historical Codex-only implementation handoff for binding native agent transcript events to orchestrator-owned graph state.
- `project_neutral-workflow-config-init.md` — historical implementation handoff for provider-native SessionStart nudges and one canonical `.coderails/workflow.config.yaml`.
- `project_codex-claude-graph-parity.md` — historical handoff for matching Claude and Codex graph behaviour while keeping both plugins independent.
- `project_mixed-provider-graph.md` — superseded historical mixed-provider design; do not implement.
- `project_pr422-e1-e3-fix.md` — PR #422 exact-head NO-GO evidence, posted artifacts, and next repair/eval steps.
- `project_pr429-execution-discipline-eval-artifact.md` — PR #429 rename and Bash fix are verified; only the exact-head eval PR artifact remains to post.
# Provider Python migration clean cutover

- `project_provider-python-migration-clean-cutover.md` — approved full migration of both providers to Python and a current-only graph contract; historical M3 graph node and resume procedure.
- `project_provider-python-migration-remote-handoff.md` — remote-branch handoff for the incomplete migration, including completed cutovers and next ordered work.
