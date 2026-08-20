# Phase 9 — Wiki + docs-sync, in full

Detail-carrier for [SKILL.md](SKILL.md)'s Phase 9. The main skill keeps the imperative (cluster
wiki ingest once at the loop end, then run `/sync-docs` once); this file is the worker-prompt
suppression mechanics, the wiki-delivery verification steps, and the docs-drift disposition rule
you consult while running it.

**Graph dispatch boundary.** The Claude-owned role map in `graph_dispatch.sh` resolves `S9-wiki`
to `wiki-writer` and `S9-docs` to `docs-auditor`. The orchestrator-side invocation sequence for
this sequential `S9-wiki -> S9-docs` link, plus the
`J12-all-units` join release that gates it, is documented in
[execution-graph.md](execution-graph.md)'s `S9-wiki -> S9-docs` and `J12-all-units` subsection, with
acceptance evidence in `hooks/scripts/tests/graph_dispatch_j12_s9.test.sh`.

**Suppressing per-PR wiki steps in spawned `/coderails:workflow` agents:** place the following line as the **FIRST instruction** in every spawned agent's prompt inside this loop (not buried mid-section, not under the task-specific scope, not after the workflow steps — first):

> "When running /workflow inside this agentic-loop, skip /workflow's wiki sub-steps (Phase 2 `/coderails:wiki-query` and Phase 5 `/coderails:wiki-ingest`/`/coderails:wiki-lint`). The orchestrator runs these at the loop boundary — running them per-PR causes redundant ingests and fragmented wiki context."

**Why first-line, not just "include":** workers shortcut past mid-section process notes and treat anything that appears to constrain the workflow steps as "optional polish." **Scope-suppression instructions go above scope-additive instructions in worker prompts.**

The orchestrator handles both ends: Phase 2 (plan-level wiki read before coding starts) and Phase 9 (cluster ingest+lint after all PRs are merged).

**Wiki commits are artifacts too — verify they reached `origin/main`, and deliver them the way *this* repo accepts.** A delegated wiki agent reports a *commit SHA*, not a merged PR — and a commit is not a push. Close two failure modes at the loop boundary: (1) the agent commits to **local `main`** and never pushes — work stranded; (2) the agent pushes wiki files **direct to `main`**, which a branch-protection ruleset rejects.

**Delivery is repo-specific.** If `main` is ruleset-protected, the wiki agent must deliver via a branch + PR off freshly-fetched `origin/main`, merged like any other change. Only where a repo *deliberately* permits direct wiki commits (e.g. a wiki dir gated behind a bypass env var) is a direct push acceptable — and even then it must be verified to have landed.

**Then verify, after `git fetch origin`:** confirm the content is on `origin/main` via the wiki PR's `mergedAt` or `git show origin/main:<wiki-file>`. Do **not** confirm a merge with `git merge-base --is-ancestor <agent-sha> origin/main` — a squash-merge rewrites the SHA, so the agent's commit is never an ancestor even when its content landed (`--is-ancestor` is the right probe only for *detecting* an unpushed commit before merge). A committed-but-unpushed SHA is a textbook false-success; the "committed" ping is a claim, not evidence (Phase 12).

**Docs-drift check — run `/sync-docs` at the loop boundary**

After the cluster wiki ingest+lint, the orchestrator runs `/sync-docs` ONCE at the loop boundary. Wiki ingest updates the external knowledge base; `/sync-docs` is the complement — it audits the repo's own in-tree docs (e.g. README.md, AGENTS.md, docs/REFERENCE.md) for drift against the just-merged code.

Run it even without Serena (the `--semantic` backend) — omit `--semantic` for the traditional file-comparison audit, which still catches drift. Do not skip `/sync-docs` just because Serena isn't installed.

Delegate it to a spawned agent, `subagent_type: coderails:docs-auditor`, at the `default` role, same as the wiki-writer agent — both inline-assigned (like Phase 2's; Phase 2.8 routes build tasks only) — to keep orchestrator context clean. **Do not substitute a generic agent for docs auditing.** In-tree documentation has repo-specific structure and conventions; a docs-auditor type knows to check against the actual repo's doc architecture, not generic drift categories.

**Disposition of findings:** `/sync-docs` surfaces drift; the orchestrator must triage. Fix only drift the loop's own PRs introduced. Surface pre-existing drift to the user rather than silently folding unrelated doc fixes into the loop — that is scope creep. This mirrors the loop's finding-triage discipline.
