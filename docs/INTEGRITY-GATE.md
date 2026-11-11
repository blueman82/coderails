# Integrity gate

The gate reads inspection and eval comments for the current PR head. A trusted GitHub workflow posts the `integrity-review` commit status.
A GitHub rule on `main` must make that status mandatory and accept it only from the `github-actions` app.

The workflow uses the built-in `GITHUB_TOKEN`. No second account, personal access token, Mac service, or sudo is necessary.

The local publication gate accepts `not_applicable` for `security-review` on standalone wiki prose in a fixed scope.
The scope identifies the live base, the unique merge base, the head, all affected page entries, and the full tracked context digest.
Explicit path groups must list all context paths other than the authored endpoints. This includes unchanged Markdown and plugin files.
The reader refuses the scope if a consumer path has no group.

In version 3, the full `consumer_scope` and each group must explicitly declare `effect_free`.
The available values are `effect_free`, `active`, and `unknown`. The initial value is `unknown`.
Known effects on execution, access control, or instructions cause a refusal. So do unknown or missing declarations, with or without full coverage and `unresolved=[]`.

The full declaration covers all M/B/H facts and the combined effects of authored M-to-H operations, live-B context, and group interactions.
Each group covers its members in the three trees and their role in that combination.
The reader refuses version 1 and 2 records. It does not supply affirmative declarations.

The checks rely on the agent to follow the rules. Full coverage cannot prove the inspection text is correct.
A change to an affected entry on the live base alone causes a refusal.

The trusted GitHub reader continues to check the ordinary general-inspection companion comment.
The `integrity-review` status cannot prove that the N/A scope is correct or that its declaration is correct.
Previous local readers reject N/A. Use a release candidate that passed its checks. Follow its installation steps before you use the new writer and reader.
Keep installation on HOLD until affected sessions stop and the checks succeed in new sessions.

Do not patch an active reader or disable a gate.

## What the workflow checks

- The inspection and eval markers name the current PR and head SHA. GitHub attributes the two comments to the current repository owner login.

- The inspection summary has the headings that the gate expects.

- The Claude and Codex post-review helpers post a comment with the pass records. Then they post a comment with the same marker and the general inspection summary.
  The gate reads the second comment. The local merge check compares the two comments for agreement.
  The gate accepts a compatibility line directly after the marker if it names the same PR and SHA.
  A malformed line or a `clean-break` count above zero causes a refusal.
  After the producers of this line reach `main`, update the gate to make the line mandatory.

- The eval has the correct structure, a frozen hash, command and control fields, and recorded results.
  Each P0 eval must have a result that shows success and records for verification.

- A version 2 eval has a signed hash that covers the freeze SHA and timestamp.
  A level 1 or 2 version 1 eval must have a signed change that names the two fields and marks timing as unverifiable.
  The workflow checks the signature bytes. It has no trusted signer list or PR branch ancestry proof.
  The local post and merge checks use the trusted signer list and check ancestry.

- The full list of changed files agrees with the PR file count and stays below GitHub's 3,000-file API cap.
  The PR cannot change the workflow, gate code, its imported Python modules, or other protected paths.
  The protected modules include `scripts/lib/artifact_io.py`, `eval_integrity.py`, `eval_signing.py`, `eval_trace.py`, and `config.py`.
  The protected paths also include package paths that could replace those imports.

- The default diff limit is 768 KiB. The gate refuses a missing diff or a diff above that limit.

- The PR targets `main`. Before it posts a status that shows success, the workflow reads all open PRs that target `main`.
  It refuses a shared head SHA. A PR that targets a different branch cannot post a status that shows success.

The workflow runs code from `main` and reads PR files and comments as data. It does not check out the PR head or run commands from eval comments.
It skips closed PRs. It reads the owner comments and PR head again before it posts a status that shows success.

One concurrency group prevents this workflow's runs from posting statuses at the same time. GitHub does not guarantee the sequence of queued runs.
A full queue can cancel a waiting run. Comment changes start a new check. An hourly run checks open PRs again if GitHub misses a change.

Each run checks the PR records. It skips the status write if the latest `github-actions[bot]` status has the same value and description.
This preserves GitHub's [limit of 1,000 statuses for one SHA and context](https://docs.github.com/en/rest/commits/statuses#create-a-commit-status).
At 900 statuses, the workflow retires the SHA with one last error status. Push a new commit to start the gate again.

If the SHA has 1,000 statuses and the latest shows success, GitHub rejects a correction. Move the PR head and examine the run with the error.

**Trust limit.** This check tests structure and consistency. A status that shows success cannot prove that the owner ran the commands or used an unaffiliated reviewer.
The owner can change one or the two comments. A comment can also change between the last read and the status post.

A new PR can briefly inherit an earlier status that shows success at the same SHA, before GitHub starts the new run.
A subsequent check or the hourly run can correct that status after an interval. If GitHub rejects the correction, the workflow cannot replace the previous success.
Examine the run with the error and the status history.

A different trusted workflow with `statuses:write` could post the same context.
The rule checks the app source, so it cannot identify a single workflow.

## Turn on the gate

1. Use the PR workflow to examine and merge this workflow and its validator.
   After the rule is active, changes to `.github/workflows/` and `scripts/integrity-gate/` cannot attest themselves.

2. Turn on the repository's GitHub automation service. Check that the workflow has only `contents:read`, `pull-requests:read`, `issues:read`, and `statuses:write`.

3. In repository Settings → `Actions` → Policies, make an **active** policy named `coderails-integrity-review-events`.
   Target only `.github/workflows/integrity-review.yml`. Set the policy to accept `pull_request_target`, `issue_comment`, `schedule`, and `workflow_dispatch`.
   The setup command checks this policy before it makes a status rule.
   [GitHub's default public-repository policy](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target#default-policy-for-pull_request_target) currently checks `pull_request_target` runs.
   GitHub plans to block them on December 2, 2026. A run that succeeds today does not prove that the run will work then.

4. If a previous integrity daemon is installed, stop it before you rely on a status from the GitHub workflow.
   Open a test PR that changes an ordinary file. Post correct current-head inspection and eval comments from the repository owner login.
   Read the workflow run and the newest `integrity-review` status on the same head SHA.
   Test a missing artifact, a marker from a different author, and a changed comment. Each must cause a newer `failure` status.

5. Preview the rule with `python3 scripts/integrity-gate/setup.py --candidate-pr <test PR number>`.
   The command refuses if the GitHub automation service is off or if it cannot find the policy. It also refuses a test PR without a correct status from the service.
   It gets the `github-actions` app ID from GitHub. It does not fall back to “any source.”

6. If the config has a previous `integrity_review.machine_user`, local merge checks continue to trust only that login.
   After you check the status from the GitHub bot, set `integrity_review.enabled: true` and remove `machine_user`.
   The local checks then trust only `github-actions[bot]`. New installs can set `enabled: true` after the bot posts a status that shows success.

7. Run the setup command with `--apply`. Read the rule in the output. Check a PR that succeeds and a PR that fails in the GitHub merge box.
   Do not merge the test PRs during this check.

The rule makes a PR and `integrity-review` mandatory on `main`. No actor can bypass it.
The setup command makes the rule only after a test PR succeeds. This keeps the repository open until the workflow can report a status.

## Change or recover the gate

The rule blocks changes to the workflow and validator. The repository owner controls the maintenance window for an update.
Record the current rule. Disable its checks. Merge the inspected change and test the new status on a safe PR. Turn the rule back on.

If a gate error blocks all merges, an administrator can disable the rule and examine the GitHub run and status history.
Turn the rule back on only after a test that succeeds and a test that fails as expected.

Earlier root-owned LaunchDaemon files remain in the tree for recovery of historical installations. The installer does not select them.
Do not run that daemon with the GitHub rule. A newer daemon status can hide a GitHub bot success on the same SHA.
