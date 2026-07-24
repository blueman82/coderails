# Tier-Gate Architecture

The tier-gate is a three-layer enforcement system that prevents dishonest or invalid tier classifications from being merged to `main`. It combines local checks, daemon evaluation, and server-side GitHub protection.

## What It Is

A **self-declared tier verification system** that validates a PR's claimed tier (0, 1, or 2) against actual code impact. The tier scale runs from least verification to most: tier 0 is an exemption from the full eval suite, tier 2 requires it.

- **Tier 0** (exempt, justified): all three hold — the change is a single work-unit, it has no outward or irreversible surface, and an existing test or verify-criterion already covers the goal state. A user-facing change is never tier 0, however trivial.
- **Tier 1** (standard): anything above tier 0 that does not meet the tier-2 predicate. This is the default for ordinary multi-step or user-facing work. A user-facing surface on its own — a UI, CLI output, a served endpoint — lands here, not tier 2.
- **Tier 2** (full suite): either the change bundles three or more independent work-units, or it carries an irreversible or external surface (publish, deploy, migration, data deletion, external send).

`scripts/tier-gate/judge-prompt.md` carries the authoritative statement of these predicates — it is what the daemon actually judges against, so read it there when the two disagree.

A PR author must run `/coderails:task-evals` to declare a tier via an `evals.json` artifact, then `/coderails:post-evals` to post it. The system then verifies the claim is honest.

## Why It Exists

**Security boundary:** Tier classification gates merge authority. A tier-0 claim means "this is a single covered work-unit, exempt from the full eval suite"; a tier-2 claim means "this is large or irreversible, run everything." The attack is therefore a *downward* forgery: claiming tier 0 on work that is really tier 1 or 2 buys an exemption the change has not earned, bypassing the eval suite via bot auto-merge or delegate-to-ci patterns. The tier-gate prevents this.

## The Three Layers

**Layer 1: Local merge.sh gate (fail-closed)**
When `config.tier_review.machine_user` is set in `.claude/workflow.config.yaml`, `scripts/merge.sh` fetches the `tier-review` commit status from GitHub and validates:
- Status exists (daemon has judged it)
- Status is `success` (daemon approved it)
- Status creator matches the configured machine user (unforgeable — only root can create)
- Description carries `verdict=legitimate` (not a laundered status)
- Description carries `tier=N` token matching the PR's claimed tier (binding)

Blocks merge if any check fails. This is redundant defence-in-depth: it fails loudly on misconfiguration and holds the line before the ruleset is active.

**Layer 2: Daemon verdict (tier-gate-runner.sh)**
A root-owned launchd process (`com.coderails.tier-gate`) runs `scripts/tier-gate/tier-gate-runner.sh` every 5 minutes. It:
- Fetches all open PRs in the watched repo
- For each PR with an `evals.json` artifact: runs the judge prompt (an LLM prompt in `scripts/tier-gate/judge-prompt.md`) to evaluate the claimed tier against the actual code diff
- Posts a `tier-review` commit status carrying a `verdict=` token and the claimed `tier=N` token. It posts on every outcome, not only on approval. The six verdicts are `legitimate` (state `success`), `illegitimate` (state `failure`), `insufficient` when the blind inputs do not support a decision either way — the judge's own verdict when a diff is empty or unreadable, and also what a tier-1 or tier-2 claim receives when the diff exceeds the size cap (a tier-0 claim over the same cap gets `illegitimate`, because size is itself a tier-0 discriminator), `self_edit` when the diff touches the tier-gate's own files, `pending` while judging is in flight, and `error` for operational failures such as an unfetchable diff or files list, a missing embedded `evals.json`, or an unusable judge response
- Only `verdict=legitimate` at state `success` satisfies the merge gate; every other status blocks

Blocks at GitHub API level: a dishonest tier can never receive a `verdict=legitimate` status.

**Layer 3: GitHub ruleset (server-side)**
When active, a GitHub ruleset on `main` requires:
- PR before merge
- `tier-review` status must be `success` (posted by the machine user)

This is the primary control, enforced at GitHub's edge — no local agent can fake a status or bypass the ruleset without write access to the GitHub API. Activation awaits owner provisioning.

## How to Find and Edit the Spec

The authoritative spec lives at `docs/coderails/specs/tier-review-spec.md`. It defines:
- The judge prompt and LLM routing
- Capability lattice: why the machine user's credentials are unforgeable
- Availability constraints (when the ruleset activates)
- Tier definitions and classification rules

Edit the spec there, then ensure `tier-gate-runner.sh` and the daemon's launchd plist stay in sync with any config changes.

## For Contributors

When you push a PR:
1. Run `/coderails:task-evals` to generate `evals.json` with a claimed tier
2. Run `/coderails:post-evals` to post it on the PR
3. Wait for the daemon to judge it (typically 5 minutes; check PR comments for `tier-review` status)
4. If the daemon approves (`verdict=legitimate`), merge normally
5. If the daemon rejects (`verdict=illegitimate`), re-read the tier rules, adjust the claimed tier or the changeset, and repost

The deny path fires when a claimed tier is dishonest: the daemon judges your change against its tier definition and posts `verdict=illegitimate`, which blocks both the local merge gate and the GitHub ruleset.
