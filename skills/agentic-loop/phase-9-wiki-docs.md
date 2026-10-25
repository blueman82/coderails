# Phase 9 — Wiki + docs-sync, in full

This file gives the steps for [SKILL.md](SKILL.md)'s Phase 9. Ingest the wiki
once at the end of the loop. Then run `/sync-docs` once. Use the instructions
below to set worker prompts, verify wiki delivery, and resolve docs drift.

**Graph dispatch boundary.** The Claude role map in `graph_dispatch.py`
assigns `S9-wiki` to `wiki-writer` and `S9-docs` to `docs-auditor`.
`J12-all-units` must release before `S9-wiki -> S9-docs` runs. See the
`S9-wiki -> S9-docs` and `J12-all-units` section of
[execution-graph.md](execution-graph.md). The acceptance test is
`hooks/scripts/tests/graph_dependencies_test.py`.

**Suppress per-PR wiki steps in spawned `/coderails:workflow` agents.** Put
the following line first after the required graph envelope in every spawned
agent prompt for this loop. Put it before task scope and workflow steps:

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/coderails:wiki-query` and Phase 5 `/coderails:wiki-ingest`/`/coderails:wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

Put that instruction first. A worker can miss a process note in the middle of
a prompt. Put instructions that restrict scope before instructions that add
scope.

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged).

**Verify wiki delivery to `origin/main`.** A wiki agent can report a commit
SHA, but a commit alone does not show delivery. The work can stay on local
`main`, or a direct push can fail under branch protection. Check the remote
content at the loop boundary.

**Use the repo's delivery rule.** If a ruleset protects `main`, create a
branch and PR from a fresh `origin/main`. Merge it through the normal gate.
If the repo permits direct wiki commits, a direct push is possible. Verify
that it landed.

**Then verify delivery.** Run `git fetch origin`. Check the wiki PR's
`mergedAt` or read `git show origin/main:<wiki-file>` to confirm that the
content reached `origin/main`.

Do **not** use `git merge-base --is-ancestor <agent-sha> origin/main` to confirm
a merge. A squash merge rewrites the SHA, so the agent's commit is not an
ancestor even when its content landed. Before merge, `--is-ancestor` can help
detect an unpushed commit. A "committed" message alone is a claim, not Phase
12 evidence of delivery.

**Docs-drift check — run `/sync-docs` at the loop boundary**

After wiki ingest and lint, run `/sync-docs` once. It checks repo docs such as
README.md, AGENTS.md, and docs/REFERENCE.md against the merged code.

Run it even without Serena (the `--semantic` backend) — omit `--semantic` for the traditional file-comparison audit, which still catches drift. Do not skip `/sync-docs` just because Serena isn't installed.

Delegate the check to a `general-purpose` agent at the `default` role. Give it
the instructions from `agents/docs-auditor.md` explicitly. Assign this role
when you spawn the agent, as for the wiki agent and the Phase 2 agent. Phase
2.8 routes build tasks only. Require the docs agent to check the repo's actual
documentation structure and conventions.

**Resolve findings.** Fix drift that the loop's PRs caused. Report earlier
drift to the user. Apply the loop's normal finding triage.
