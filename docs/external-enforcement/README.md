# External enforcement (opt-in, inert by default)

Nothing here runs today. No live ruleset exists, GitHub Actions is disabled, nothing is under `.github/workflows`,
and the integrity daemon is not used. These artifacts exist so a human can turn on server-side enforcement later.

| File | Role |
| --- | --- |
| `ruleset.json` | Main-branch ruleset: PR required, merge method `merge` only, 0 required approvals, no force-push, no deletion, required status check `verify` pinned to `integration_id` 15368 (the GitHub Actions app, so a forged commit status or another app cannot satisfy it), empty bypass list. No `required_linear_history` (it would forbid the merge commits `scripts/merge.py` makes with `gh pr merge --merge`). |
| `verify.yml.template` | Workflow that runs `scripts/ci_verify.py`. Outside `.github/workflows`, so it is inert. |
| `scripts/external_enforcement.py` | `plan` (read-only diff against the live ruleset) and `apply --yes`. |
| `scripts/ci_verify.py` | Runs the pre-commit suites, then the existing SHA-bound review/eval gates and `smoke_verify` for an exact head. |

Approvals stay at 0 because the identity that opens a PR cannot approve it, so any higher count would lock every PR.

## Reason codes

`external_enforcement.py`: `DRY_RUN`, `NO_YES`, `CHECK_NEVER_SEEN`, `TEMPLATE_MISSING`, `NO_DIFF`, `APPLIED`, `GH_FAIL`.
`apply` refuses with `CHECK_NEVER_SEEN` unless a completed, successful `verify` run from the GitHub Actions app was observed on a recent commit (a plain status, a red or pending run, or another app's run does not count), because
requiring a check that never posts blocks every merge, including `scripts/merge.py`.
`ci_verify.py`: `OK`, `SUITE_FAIL`, `REVIEW_ABSENT`, `EVAL_ABSENT_OR_NOGO`, `FETCH_FAIL`, `SHA_MISMATCH`, `SMOKE_FAIL`.
"Stale" means an artifact bound to an older head SHA (existing `matches_marker` behaviour); there is no time-based expiry.
Integrity attestation is skipped by design (no `machine_user` configured, so `integrity_reason` returns empty).

## Trust analysis (read before enabling)

Enforced outside the agent process:

- The GitHub server-side rule: no direct push to `main`, no force-push, no deletion, and no merge until `verify` is green.
- The runner's re-execution: `ci_verify.py` re-runs the suites and `smoke_verify` on a machine the agent does not drive.
  The template checks out the BASE ref into `base/` and runs `base/scripts/ci_verify.py` and the quality checker from
  there, treating the PR head (`head/`) as data, so a PR cannot rewrite those scripts to pass itself.

NOT enforced:

- The verifier code is also PR-controlled in part: `hooks/scripts/tests/run_all.py` and the suites it runs are executed
  from the PR head (they must run beside their own tests), and `smoke_verify` runs eval commands from the PR's own
  comment. A PR can alter its own tests. Only a second identity reviewing test changes closes that. Likewise, once
  the workflow file is merged, a PR that edits `.github/workflows/verify.yml` runs its own edited version.
- The artifact trust root is still the shared `gh` login. `trusted_comment_bodies` trusts comments by the authenticated
  user with WRITE, MAINTAIN or ADMIN, and the agent and the human share that login. The agent can post a review or GO
  eval comment itself. Only `smoke_verify`'s re-execution is independent, and it runs commands that come from that
  same comment.
- An admin using the same token can edit or delete the ruleset. Real independence needs the bypass list kept empty
  AND a second GitHub identity doing the merge (and holding the admin rights the agent lacks).
- The workflow template lives in the repo; a same-user agent can edit it in a PR. Only a second identity reviewing
  workflow changes closes that.

Accepted risks:

- `smoke_verify` executes eval commands taken from a PR comment on the runner. Keep no secrets on the runner.
- It needs full history (`fetch-depth: 0`) because it runs `git fetch origin <sha>` and adds a worktree.
- `GITHUB_TOKEN` usually fails `gh api user`; the template therefore pins `_PR_TRUSTED_LOGIN` and
  `_PR_TRUSTED_PERMISSION`. Edit the login in the template if the repo owner changes.

Limited mode: if no independent runner or merger exists (second identity, or a host the agent's token cannot
control), `ci_verify.py` and the template give false assurance. Use only `ruleset.json` and `plan`, which add just
"PR required, no force-push, no delete" over `scripts/merge.py`, and delete the other two.

## Turn on (human steps)

1. Copy `docs/external-enforcement/verify.yml.template` to `.github/workflows/verify.yml`, commit through a PR.
2. Re-enable Actions: `gh api -X PUT repos/<owner>/<repo>/actions/permissions -F enabled=true`.
3. Wait for one green `verify` run on a PR.
4. `python3 scripts/external_enforcement.py plan`, read the diff, then `python3 scripts/external_enforcement.py apply --yes`.

## Turn off

Delete the ruleset (`gh api -X DELETE repos/<owner>/<repo>/rulesets/<id>`), disable Actions
(`gh api -X PUT repos/<owner>/<repo>/actions/permissions -F enabled=false`), and remove `.github/workflows/verify.yml`.

## Observability

Both scripts append advisory, fail-open trace rows (`external-enforcement/trace.jsonl` under the agentic-loop state
dir, one `event_id` each). `scripts/measure_graph_alignment.py --json` reports them under `external_enforcement`,
deduped by `event_id`. See the runbook entry "External enforcement refusals".
