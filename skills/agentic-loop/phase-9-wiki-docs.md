# Phase 9 — Wiki + docs-sync, in full

This file gives the steps for Phase 9 in [SKILL.md](SKILL.md). At the end of the loop, update the wiki one time for the PR cluster. Then run `/sync-docs` one time. Read this file during Phase 9 for the worker prompt, wiki publication checks, and the rule for corrections to the repository docs.

**Roles for graph nodes.** The Claude-owned role map in `graph_dispatch.py` resolves `S9-wiki`
to `wiki-writer` and `S9-docs` to `docs-auditor`.

The orchestrator-side invocation sequence for
this sequential `S9-wiki -> S9-docs` link, plus the
`J12-all-units` join release that gates it, is documented in
[execution-graph.md](execution-graph.md)'s `S9-wiki -> S9-docs` and `J12-all-units` subsection.

The dependency tests are in `hooks/scripts/tests/graph_dependencies_test.py`.

**Skip wiki steps for individual PRs in `/coderails:workflow` agents.** Copy the line below as the **first instruction after the required graph envelope** in each agent prompt. Put it before the task scope and workflow steps.

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/coderails:wiki-query` and Phase 5 `/coderails:wiki-ingest`/`/coderails:wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

Put that instruction first. A worker can miss an instruction in the middle of
a prompt. Put instructions that restrict scope before instructions that add
scope.

The orchestrator reads the wiki for planning in Phase 2 before coding starts. It updates and lints the wiki for the cluster in Phase 9 after all PRs merge.

**Check that wiki commits are on `origin/main`.** Use the method this repo permits for wiki updates. A delegated wiki agent reports a *commit SHA*. Check that it pushed the commit, and check the merge if it opened a PR. A commit to **local `main`** can stay local. A branch-protection ruleset can refuse a push **direct to `main`**.

**Follow the repo policy for wiki updates.** If a ruleset protects `main`, the wiki agent must use a branch and PR. Fetch `origin/main` before making the branch. Follow the usual procedure to merge the PR. Push directly only if the repo explicitly permits direct wiki commits. For example, a wiki directory can use a bypass environment flag.

For a direct push, also check that the commit is on the remote branch.

**Then check the wiki repository.** Set `wiki_repo` to the absolute wiki repo or worktree path reported by the wiki writer. Replace the PR number, unique text and wiki file path in this command:

```bash
wiki_repo="<absolute wiki repo or worktree path>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <wiki-PR-number> --repo "$wiki_repo" --grep '<text unique to the page>' --path '<wiki page path>'
```

The script fetches the wiki PR's base, checks `mergedAt` and merge-commit reachability, and checks the page content on that base. Ancestry of the agent's own commit is not proof: a squash merge rewrites the SHA. The script trusts ancestry only for a two-parent merge commit, the same rule as `verify-merged-pr`. Use `git merge-base --is-ancestor` only to find an unpushed commit before merge. For Phase 12, use the result of the remote check. A local commit SHA alone cannot show publication.

**Docs-drift check — run `/sync-docs` at the loop boundary**

After the wiki update and lint for the cluster, the orchestrator runs `/sync-docs` one time. Wiki ingest updates the external knowledge base. The `/sync-docs` command compares the merged code with repository docs such as `README.md`, `AGENTS.md`, and `docs/REFERENCE.md`.

If Serena is unavailable, run the traditional file-comparison audit without `--semantic`. That audit can find differences.

To keep the orchestrator context small, delegate the audit to an agent with `subagent_type: general-purpose`. **Include the instructions from `agents/docs-auditor.md` in the prompt.** Give this agent the `default` role, as for the wiki-writer. Set the two roles in the prompts as in Phase 2. Phase 2.8 sets roles only for build tasks.

Tell the auditor to check the repo's documentation structure and conventions. The provider label does not show that the agent did the checks.

**How to use the audit results.** The orchestrator examines the differences that `/sync-docs` reports. Correct only the differences that the loop's PRs introduced. Tell the user about pre-existing differences. Keep unrelated corrections out of this loop, as for other results.
