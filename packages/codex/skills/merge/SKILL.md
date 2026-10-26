---
name: merge
description: Merge an approved GitHub pull request only after current-head Codex review and eval evidence pass, then synchronize the main branch.
---

# Merge an approved pull request

Use this skill when the user asks to merge a pull request by number, branch name, or the current branch.

## Before merging

1. Resolve the target from the user's request. If no target was supplied, use the current branch when it has an open pull request; otherwise use `request_user_input` to ask for the pull request number or branch.
2. Fetch the pull request's current head SHA and state. Stop if it is closed without being merged.
3. If the repository requires approval, confirm the pull request is approved.
4. Confirm an independent Codex review covers the current head. When fresh review is needed, run `source-auditor` through `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role source-auditor --prompt-file <file> --cwd <exact-head-worktree>` per [guarded role sessions](../using-coderails/references/guarded-role-sessions.md); use native `spawn_agent` for `spec-reviewer`. Resolve all blocking findings, push any fixes, and repeat the review against the new head.
5. Invoke `$coderails-codex:post-review` for the final head so the trusted SHA-bound review artifact exists.
6. Invoke `$coderails-codex:task-evals`, run the frozen evals, and invoke `$coderails-codex:post-evals` for the same final head. A justified verification-level-0 result is valid only when that workflow records it as `GO`.

Do not merge when GitHub state cannot be fetched, approval is missing when required, review or eval evidence is missing or stale, an eval is `NO-GO`, smoke verification fails, or a configured integrity attestation or wiki-debt gate fails. Do not substitute local files or model claims for posted current-head evidence.

## Merge and synchronize

Resolve [merge.py](../../scripts/merge.py) relative to this `SKILL.md`. Run `python3 <absolute package-local merge.py> <PR number, branch, or auto>`. When `action_authority: enforce` applies, fetch the current head SHA and add `--expected-head <40-hex SHA>`. Mint any required receipt for this exact `python3` command, including the absolute helper path and SHA. Direct executable invocation has a different command hash and is unsupported in enforce mode. Do not reconstruct the helper's checks manually or bypass a failure. The `action_authority_gate` hook can consume a receipt before the helper; the helper checks it again when run directly.

For a graph work unit, add `--unit <id> --progress <absolute progress.json>`. The default-on diff manifest gate checks the PR head and the frozen unit manifest. The Codex `pr_publication_gate` hook checks direct merges.

Run `merge.py --describe` to read the gate list the helper enforces. It prints JSON generated from the registries the script actually runs (the verify stages, then the publication gate checks), contacts no remote, and exits 0, so the list cannot drift from the code. After every gate passes the helper merges remotely, synchronizes the repository's main branch and removes the merged branch where safe, without reporting an already successful merge as failed when another worktree still holds the local branch.

Report the pull request number, merged head SHA, final branch state, and any branch cleanup warning.
