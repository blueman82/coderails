---
name: post-evals
description: Validate and post a fail-closed, SHA-bound eval summary as durable evidence on a GitHub pull request.
---

# Post evals

Post an existing `evals.json` as a machine-marked pull-request comment. Local or committed eval files are working material, not PR-readiness evidence.

Accept a pull-request number from the user's request. Before running any command, inspect it and require a non-empty digits-only value. Stop without interpolating it if invalid; the script validates it again in code (`pr_number_invalid`) before any `gh` call.

Use the package-local [post_evals.py](../../scripts/post_evals.py), resolving its path from this `SKILL.md` rather than from the current working directory.

## Procedure

1. Locate the existing `evals.json` produced for this pull request. Do not create or rewrite its claimed results.
2. Run `python3 <resolved post_evals.py> post <pr> <evals_json>`, adding `--progress <progress.json>` for loop work (its `work_units` raise the derived minimum level). Do not run the individual validation, marker or `gh` steps by hand.
3. The script fetches the current head with `gh pr view <pr> --json headRefOid -q .headRefOid` (an empty value or fetch failure stops it), then runs the structure gate (PR-head binding, recorded smoke evidence, current command/control execution, suite integrity and the derived minimum `verification_level`), the discriminating gate and the embed gate, and computes the result; a hand-written result is never accepted.
4. It refuses with a stable reason code: `level_below_derived`, `suite_hash_mismatch`, `chain_broken`, `integrity_stripped`, `not_frozen`, `pr_number_invalid`, `stale`. The marker must remain bound to the validated pull request and its currently fetched head.
5. The body it builds starts with the unchanged `coderails-eval-summary v1` marker, then a `coderails-eval-facts v1` line (`derived_min_level`, `late_freeze`, `suite`), the P0/P1 summary with amendments for human context, and the complete source `evals.json` in one fenced `json` block with a code-stamped `gate_facts` block. It reuses an identical existing artifact instead of posting a duplicate and posts with `gh api`, never `gh pr comment`.
6. Report the comment URL, computed result, verification level, derived minimum level and current head SHA the script printed. Treat any non-zero exit as `NO-GO`; do not claim an artifact exists.

Never treat missing, stale, mismatched, rejected, untrusted, or unavailable evidence as success.
