# Integrity gate

The gate reads review and eval comments for the exact pull request head. A
trusted GitHub Actions workflow posts the `integrity-review` commit status. A
GitHub rule on `main` must require that status. The rule must bind it to the
GitHub Actions app.

The workflow uses the built-in `GITHUB_TOKEN`. You do not need a second account,
a personal access token, a Mac service, or sudo.

## What the workflow checks

- The review and eval markers name the current PR and head SHA. Both
  comments come from the live repository owner login.
- The review summary has the required headings.
- The current Claude and Codex post-review helpers write a marker and summary.
  The gate accepts those existing comments. It also accepts a newer
  compatibility line directly after the marker when that line names the same
  PR and SHA. A malformed line fails. A `clean-break` finding count above zero
  also fails. When the compatibility-line producers reach `main`, update the
  gate to require that line.
- The eval has a valid structure and a frozen hash. It has command,
  control, and result fields. Every P0 eval has a pass result and evidence.
- The changed-file list matches the PR file count. It stays below GitHub's
  3,000-file API cap. The PR cannot change the workflow, gate code, imported
  Python modules, or other protected paths. Protected modules include
  `scripts/lib/artifact_io.py`, `eval_integrity.py`, `eval_signing.py`,
  `eval_trace.py`, and `config.py`. Package paths that could replace those
  imports are also protected.
- The diff is present and below the byte limit.
- The PR targets `main`. Before a pass, the workflow reads all open PRs
  that target `main`. It rejects a head SHA shared with another PR. A PR
  that targets another branch cannot receive a passing status.

The workflow runs code from `main`. It reads PR files and comments as data. It
never checks out the PR head or runs a command from an eval comment. It skips
closed PRs. Just before posting a passing status, it reads the owner comments
and PR head again.

One concurrency group prevents this workflow from posting statuses at the
same time. GitHub does not guarantee the order of queued runs. A queue can
overflow and cancel a waiting run. Comment changes trigger a new check. An
hourly run checks open PRs again if GitHub misses an event.

After checking the evidence, the workflow skips the status write if the latest
Actions bot status already has the same state and description. This preserves
GitHub's [1,000-status limit per SHA and context](https://docs.github.com/en/rest/commits/statuses#create-a-commit-status).
At 900 statuses, the workflow retires the SHA with a final error status. Push
a new commit to restart the gate. If a SHA already has 1,000 statuses and its
latest status passes, GitHub will reject a correction. Move the PR head and
inspect the failed run.

**Trust limit:** This is a structure and consistency check. A passing status
does not prove that the repository owner ran the commands or used an independent
reviewer. The owner can change either comment. A comment can also change after
the final read and before the status post.

A newly opened PR can briefly inherit an earlier passing status at the same
SHA before its event runs. The next event or hourly run can correct that
status, but there is a delay. If GitHub rejects the new status, the workflow
cannot replace an old success. Inspect the failed run and status history.
Another trusted workflow with `statuses:write` could post the same context;
the app source rule cannot identify one workflow.

## Turn on the gate

1. Merge and review the workflow and validator through the existing PR
   process. Once the rule is active, changes under `.github/workflows/`
   and `scripts/integrity-gate/` cannot attest themselves.
2. Enable GitHub Actions. Check that the workflow has only
   `contents:read`, `pull-requests:read`, `issues:read`, and
   `statuses:write` permissions.
3. In repository Settings → Actions → Policies, create an **active** policy
   named `coderails-integrity-review-events`. Target only
   `.github/workflows/integrity-review.yml`. Allow `pull_request_target`,
   `issue_comment`, `schedule`, and `workflow_dispatch`. The setup command
   checks this policy before it creates a status rule.

   [GitHub's default public-repository policy](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target#default-policy-for-pull_request_target)
   currently evaluates `pull_request_target` runs. It is scheduled to
   block them on December 2, 2026. A passing run today does not prove the
   event will run after that date.
4. Stop an old integrity daemon before relying on an Actions status. Open
   a test PR that changes an ordinary file. Post valid review and eval
   comments for its current head from the repository owner login. Read the
   Actions run and newest `integrity-review` status for that head. Test a
   missing artifact, a foreign author's marker, and an edited comment.
   Each case must produce a newer failure.
5. Preview the rule with
   `python3 scripts/integrity-gate/setup.py --candidate-pr <test PR number>`.
   The command rejects disabled Actions, an absent event policy, or a test
   PR without a valid Actions status. It asks GitHub for the Actions app ID.
   It does not accept "any source" as a fallback.
6. An old `integrity_review.machine_user` setting makes local merge checks
   trust only that login. After the Actions bot status passes, set
   `integrity_review.enabled: true` and remove `machine_user`. The local
   checks then trust only `github-actions[bot]`. New installs can enable
   the check after the bot status passes.
7. Run the setup command with `--apply`. Read the returned rule. Check one
   passing and one failing PR in GitHub's merge box. Do not merge the test
   PRs as part of this check.

The rule requires a PR and `integrity-review` on `main`, with no bypass actor. A test PR must pass before the rule is created, so the setup does not lock the repository before the workflow can report a status.

## Change or recover the gate

The rule blocks changes to the workflow and validator. To update them,
record the current rule and disable enforcement during an owner-managed
maintenance window. Merge the reviewed change. Test its status on a safe
PR, then restore enforcement. If the gate blocks all merges, an
administrator can disable the rule and inspect the Actions run and status
history. Restore the rule only after a new passing and failing test.

Older root-owned LaunchDaemon files remain for recovery of historical
installs. The installer does not select them. Do not run that daemon with
the GitHub Actions rule. A newer daemon status can hide an Actions bot
success on the same SHA.
