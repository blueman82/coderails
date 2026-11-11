---
name: merge
description: Merge an approved GitHub pull request only after current-head Codex review and eval evidence pass, then synchronize the main branch.
---

# Merge an approved pull request

Use this skill when the user tells you to merge a PR by number, by branch name, or from the current branch.

## Before merging

1. Use the target the user supplies. If there is none, use the current branch if it has an open PR.
   If the current branch has no open PR, use `request_user_input` to get the PR number or branch.

2. Fetch the PR's current head SHA and status. Stop if it is closed without a merge.
3. If repository rules make approval mandatory, check that the PR has approval.
4. Check that Codex independently examined the current head.
   If a new inspection is necessary, use the [guarded role sessions](../using-coderails/references/guarded-role-sessions.md) instructions.
   Run `source-auditor` through `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role source-auditor --prompt-file <file> --cwd <exact-head-worktree>`.
   Use native `spawn_agent` for `spec-reviewer`.

   Correct all blocking results, push corrections, and examine the new head again.

5. Invoke `$coderails-codex:post-review` for the last head. This posts the trusted inspection artifact bound to that SHA.
6. Invoke `$coderails-codex:task-evals`. Run the frozen evals and invoke `$coderails-codex:post-evals` for the same head.
   Accept a justified verification-level-0 result only if that workflow records `GO`.

Merge only if GitHub status is available and the PR has approval if necessary.
You must have inspection and eval records for the current head. Do not merge with a `NO-GO` result.
Smoke verification and the configured integrity attestation and wiki-debt checks must succeed.
Use posted records for the current head. Local files and model claims do not satisfy the gate.

## Merge and synchronize

Find [merge.py](../../scripts/merge.py) relative to this `SKILL.md`.
Run `python3 <absolute package-local merge.py> <PR number, branch, or auto>`.
`action_authority` defaults to `enforce`. In that mode, fetch the current head SHA and add `--expected-head <40-hex SHA>`.
The owner must use `approve-action` at their terminal for the same `python3` command with the absolute helper path and SHA.

A usable key without passphrase protection or a key available through an agent can work without a passphrase.
A session autonomy grant does not replace this receipt.
Do not make a PTY or invoke the signing function to impersonate owner approval.
Explicit project settings `advisory` and `off` stay available.
The direct executable command has a different command hash. The `enforce` mode does not accept it.

Do not reconstruct the helper's checks by hand. Do not bypass an error.
The `action_authority_gate` hook can consume a receipt before the helper. The helper checks it again if you run it directly.

For a graph work unit, add `--unit <id> --progress <absolute progress.json>`. The default-on diff manifest gate checks the PR head and the frozen unit manifest. The Codex `pr_publication_gate` hook checks direct merges.

Run `merge.py --describe` to read the helper's gate list.
It prints JSON from the registries the script uses: the verification steps, then the publication gate checks.
It contacts no remote and exits 0. The same registries supply the gate list and the checks.

If all gates succeed, the helper merges remotely, synchronizes the repository's `main` branch, and removes the merged branch where safe.
If a different worktree holds the local branch, the helper can report a cleanup problem. It reports the merge as a success.

Report the PR number, merged head SHA, last branch status, and branch cleanup warnings.
