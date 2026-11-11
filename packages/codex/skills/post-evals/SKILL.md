---
name: post-evals
description: Validate and post a fail-closed, SHA-bound eval summary as durable evidence on a GitHub pull request.
---

# Post evals

Post an existing `evals.json` as a PR comment with a machine-readable marker.
Local or committed eval files do not show that a PR is prepared to merge.

Get the PR number from the user. Before you run a command, check that it contains one or more digits and no other characters.
If the value is invalid, stop without using it.
The script checks the value again before it runs `gh`. It gives `pr_number_invalid` if the check fails.

Use the package-local [post_evals.py](../../scripts/post_evals.py), resolving its path from this `SKILL.md` rather than from the current working directory.

## Procedure

1. Find the existing `evals.json` for this PR. Do not make or rewrite the results it claims.
2. Run `python3 <resolved post_evals.py> post <pr> <evals_json>`, adding `--progress <progress.json>` for loop work (its `work_units` raise the derived minimum level). Do not run the individual validation, marker or `gh` steps by hand.

3. The script fetches the current head with `gh pr view <pr> --json headRefOid -q .headRefOid`.
   It stops if it cannot fetch the value or the value is empty.
   The structure gate checks the PR-head binding, smoke records, suite integrity, and derived minimum `verification_level`.
   It runs the current command and control as part of this check.
   The script then runs the discriminating gate and embed gate.
   It calculates the result. It does not accept a result that someone wrote by hand.

4. The marker must stay bound to the validated PR and its current fetched head.
   The script gives a stable code if it refuses.
   The codes are `level_below_derived`, `suite_hash_mismatch`, `chain_broken`, `integrity_stripped`, `not_frozen`, `pr_number_invalid`, and `stale`.

5. The comment starts with the unchanged `coderails-eval-summary v1` marker.
   Next it has a `coderails-eval-facts v1` line (`derived_min_level`, `late_freeze`, `suite`).
   Then it has the P0/P1 summary with changes for human context.
   It embeds the full source `evals.json` in one fenced `json` block with a `gate_facts` block from the script.
   It uses the existing artifact if its contents are the same. It posts with `gh api`, without `gh pr comment`.

6. Report the comment URL, calculated result, verification level, derived minimum level, and current head SHA from the script output.
   If the exit status is not 0, report `NO-GO`. Do not claim that an artifact exists.

Report success only if the script accepts a current, trusted record that agrees with the PR.
If there is no record, or if it is stale, rejected, or unreadable, do not report success.
