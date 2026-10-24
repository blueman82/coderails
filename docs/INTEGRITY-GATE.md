# Integrity gate

The gate reads review and eval comments for the exact pull request head. A trusted GitHub Actions workflow posts the `integrity-review` commit status. A GitHub rule on `main` must require that status and bind it to the GitHub Actions app.

The workflow uses the built-in `GITHUB_TOKEN`. You do not need a second account, a personal access token, a Mac service, or sudo.

## What the workflow checks

- The review and eval markers name the current PR and head SHA. GitHub attributes both comments to the live repository owner login.
- The review summary has the required headings.
- The eval has a valid structure, a frozen hash, command and control fields, and recorded results. Every P0 eval has a passing result and evidence.
- The complete changed-file list matches the PR file count and stays below GitHub's 3,000-file API cap. The PR does not change the workflow, gate code, or other protected paths.
- The diff is present and below the byte limit.

The workflow runs code from `main`. It reads PR files and comments as data. It never checks out the PR head or runs a command from an eval comment. It reads the owner comments and PR head again just before it posts a passing status. One concurrency group prevents runs of this workflow from posting statuses at the same time. GitHub does not guarantee the order of queued runs. A queue can overflow and cancel a waiting run. Comment changes trigger a new check. An hourly run checks open PRs again if GitHub misses an event.

**Trust limit:** This is a structure and consistency check. A passing status does not prove that the repository owner ran the commands or used an independent reviewer. The owner can change either comment. A comment can also change after the final read and before the status post. The next event or hourly run will correct that status, but there is a delay. Another trusted workflow with `statuses:write` could post the same context; the app source rule cannot identify one workflow.

## Turn on the gate

1. Merge and review this workflow and its validator through the existing PR process. Changes to `.github/workflows/` and `scripts/integrity-gate/` cannot attest themselves after the rule is active.
2. Enable GitHub Actions for the repository. Check that the workflow has only `contents:read`, `pull-requests:read`, `issues:read`, and `statuses:write`.
3. Open a test PR that changes an ordinary file. Post valid current-head review and eval comments from the repository owner login. Read its Actions run and the newest `integrity-review` status on its exact head. Test a missing artifact, a foreign author's marker, and a changed comment; each must produce a newer failure.
4. Preview the exact rule with `python3 scripts/integrity-gate/setup.py --candidate-pr <test PR number>`. The command refuses a disabled Actions setting or a test PR without a valid GitHub Actions status. It looks up the GitHub Actions app ID from GitHub. It never falls back to “any source.”
5. Run the same command with `--apply`. Read the returned rule. Check a passing and a failing PR in the GitHub merge box. Do not merge either test PR as part of this check.
6. If local Coderails merge checks should also require this status, set `integrity_review.enabled: true` in the project's workflow config after the server rule is active.

The rule requires a PR and `integrity-review` on `main`, with no bypass actor. A test PR must pass before the rule is created, so the setup does not lock the repository before the workflow can report a status.

## Change or recover the gate

The rule blocks changes to the workflow and validator. For an update, use an owner-managed maintenance window: record the current rule, disable its enforcement, merge the reviewed gate change, test the new status on a safe PR, and restore enforcement. If a gate failure blocks all merges, an administrator can disable the rule and inspect the Actions run and status history. Restore the rule only after a new passing and failing test.

Older root-owned LaunchDaemon files remain in the tree for recovery of historical installs. The product installer does not select them. Do not start that daemon while the GitHub Actions rule is active.
