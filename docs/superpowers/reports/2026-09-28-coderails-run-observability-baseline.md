# Post-cutover run observability baseline

## Validation checklist

- [x] Freeze the UTC window and provider set before counting; define a native session and exclusions.
- [x] Give each metric its counting rule, numerator, denominator, rate, source, method, and basis. Mark the basis `observed`, `derived`, or `manual`. Use `unavailable` when the required independent audit was not done.
- [x] Keep `work_units` and graph nodes separate. Treat `eval_refs` as evaluation references, not a mapping.
- [x] Keep frozen loop cost apart from transcript token usage and active engineering minutes.
- [x] Check every positive claim against a native artifact or the two post-cutover commits. Set no operational target.

## Frozen cohort and inventory

**Window:** 2026-09-28 11:32:24 UTC through 2026-09-28 22:51:05 UTC, inclusive. The window starts at cutover merge `e1090098` and ends at the census freeze.

**Providers:** native Claude Code and native Codex. A session enters this cohort by its native start time and a Coderails repository working directory. Count each worker as a native session, separate from its parent. A loop is not a session. Events added after the cutoff are outside this census, even when their session started earlier. This is a start cohort. It does not include every session active during the window.

| Native source | Candidate files | Included sessions | Exclusions | Basis |
| --- | ---: | ---: | --- | --- |
| Codex `~/.codex/sessions/2026/09/28/*.jsonl` | 81 | 56: 2 roots, 54 workers | 5 started before cutover; 17 other working directories; 3 Coderails wiki working directories | Observed `session_meta.payload.id`, `timestamp`, `cwd`, `parent_thread_id`; parsed first record of each file. All 54 included workers name an included parent. |
| Claude `~/.claude/projects/**/*jsonl` with `coderails` in its path | 632 | 0 | 630 started before cutover; 2 lack a usable `sessionId` plus `cwd` record | Observed first record carrying `sessionId`, `cwd`, `timestamp` in each path-matched file. The 2 unresolved files are excluded, not treated as clean sessions. |
| **Combined** | **713** | **56** | **657** | Derived sum of the two native inventories. |

The working-directory rule accepts `/Users/harrison/Github/coderails` and its Coderails worktrees. It excludes `/Users/harrison/Github/coderails-wiki`.

The two Codex roots are `01a0e7ed-3515-7e73-a760-cfb2bd8c4763` (12:11:17 UTC) and `01a0ea0d-1a4e-7480-98b5-a1e7931a13a2` (22:05:22 UTC). Their native rollout files are under the Codex source root above. The second root was still running at the census. It cannot enter a completed-outcome audit.

A later Codex rollout started at 22:55:37 UTC, after the cutoff. This explains why the directory now has 82 files, while the cutoff inventory has 81. These counts describe local artifacts. They do not imply that deleted historical sessions were recovered. No source manifest gives a deleted-file count, so that exclusion count is unavailable.

## Metric record, version 1

`N/D` gives the counted numerator over the eligible audited denominator.
`Unavailable` means required evidence or an independent check is absent. It
never means zero. Rates appear only where both counts have support. All rows
use the frozen cohort above. Source paths and identifiers point to evidence;
they do not replace the native records.

| Metric | Numerator / denominator | Rate |
| --- | --- | --- |
| State divergence | Unavailable / 0 | Unavailable |
| Duplicate mutation | Unavailable / 0 | Unavailable |
| Repair incidents | Unavailable / 0 | Unavailable |
| False completion blocks | Unavailable / 0 | Unavailable |
| False completion passes | Unavailable / 0 | Unavailable |
| Adapter/test duplication | Unavailable / 0 | Unavailable |
| Repeated state-view updates | Unavailable / 0 | Unavailable |
| Maintenance time | Unavailable / 0 | Unavailable |

### Metric rules and evidence

**State divergence.** Count mismatches only for declared relationships between work units and nodes. Divide by independently inspected declared relationships. None was found in the inspected graph snapshots, so no divergence audit is possible. The first root's current `~/.coderails/agentic-loop/-Users-harrison-Github-coderails-.git/01a0e7ed-3515-7e73-a760-cfb2bd8c4763/progress.json` has one work unit and one graph node. That snapshot does not establish their census-time counts. The second root's frozen `evals.json` (22:09:49 UTC) describes seven dependent work units. Its current `progress.json` still has seven work units. Its graph changed after the census, and no durable census-time node count was found. Report that count as unavailable. The two structures are separate inventories. `eval_refs` does not map them. Other cohort sessions without an inspected graph are outside this relationship inventory.

**Duplicate mutation.** Count same-target, same-operation retries that an independent audit confirms repeated an accepted change. Divide by independently audited mutation sequences. Exclude rejected calls and retries needed to finish a transition. A manual incident audit is required. Neither transcript commands nor current graph snapshots prove a prior accepted mutation was repeated. Sources are the Codex native rollouts and graph snapshots above. No independent sequence audit or incident record was available. All 56 sessions remain unaudited for this metric.

**Repair incidents.** Count independently grouped repair episodes. Divide by root sessions independently inspected for repair history. Count multiple commands in one episode once. No root repair history was independently audited and grouped. Candidate R1 is outside the numerator. It concerns root `01a0e7ed-3515-7e73-a760-cfb2bd8c4763`. The worker report describes active-wave identity and Codex state-write defects. It records hard-stop and invalid-proposal triggers, repair commit `cdf6bdf1`, and regression cases. Sources are `/private/tmp/coderails-post-cutover-state-worker-report.md`, `git show cdf6bdf1`, and the archived `01a0e7ed-3515-7e73-a760-cfb2bd8c4763-completed-post-cutover-state-defects-20260928-01/retro.json` under the loop root above. These sources document repair work. They do not establish all incidents for that root or the metric denominator. The active second root and 54 workers were not independently audited for separate episodes.

**False completion blocks.** Count blocks independently shown to violate their documented gate condition. Divide by completion blocks replayed from exact source artifacts. No such replay was completed. A `GO` in the first root's `evals.json` and `complete` in its `progress.json` are provider evidence. They are not an independent replay. The active root is outside completion-outcome measurement.

**False completion passes.** Count successful completions independently shown to violate a required condition. Divide by successful completions independently audited. No complete set of conditions was replayed against the exact native transcript, proof, eval, and retro artifacts. Sources are the first root's `progress.json`, `evals.json`, `proof.json`, and `retro.json`. The second root was active. A provider's completion claim is not an independent pass audit.

**Adapter/test duplication.** Count duplicated semantic cases across provider-specific tests. Divide by shared semantic changes whose provider-specific cases were compared independently. The footprint below is observed, but no semantic-case comparison was completed. Required provider-native evidence handling is excluded by definition. Source: `git show --numstat cdf6bdf1 a275153d`. Uncommitted provider work at census is excluded because its change boundary was not frozen.

**Repeated state-view updates.** Count audited work items that needed manual status changes in both `work_units` and graph nodes. Divide by items whose owner intended both views to represent the same decision. No owner-declared pairing or action-level audit exists. Equal snapshot counts do not establish duplicate updates. Sources are the two root `progress.json` snapshots above. Unpaired entries and other sessions are excluded.

**Maintenance time.** Count recorded active engineering minutes by category. Divide by graph changes with a contemporaneous manual task-time record. No active-minute record was found for shared kernel, Claude adapter, Codex adapter, tests, or repair. Commits `cdf6bdf1` and `a275153d`, the worker report, and retros record work and verification. They do not record active minutes. Transcript token usage and frozen `retro.cost` measure something else; do not convert them to minutes.

### Documented repair candidate and duplication footprint

The worker report groups two corrected defects in one work unit. It records regression checks before and after commit `cdf6bdf1`. The archived state-defects retro repeats that repair scope. These records form candidate R1. It remains outside the independently audited incident numerator. The same root later had a stranded fixture loop and recovery. No independent audit established the number of repair episodes for that root. The report therefore gives no positive numerator or rate.

The observed diff for `cdf6bdf1` changed the maintained `packages/graph-semantics/graph_semantics.py` and both provider copies. Each file gained 5 lines and lost 7 lines. The diff also added 41 lines in `packages/tests/test_provider_graph_lifecycle.py`, 16 in `packages/tests/test_codex_graph_runtime.py`, and 2 in the Codex graph adapter.

The later fixture commit `a275153d` added 38 one-line shared fixtures under `packages/graph-semantics/fixtures/`. Its committed diff added no provider-specific cases. These are file and line counts for two commits. They are not a duplicated-case rate. A comparison of semantic test cases and a record of adapter maintenance time are unavailable.

## Coverage and audit limits

The session census uses readable local native files and the frozen start window. Some metric denominators are smaller because they require independent inspection. The first completed root has a documented repair candidate but no independent incident-history audit. The other root was active at cutoff. The repair metric has no independently audited root.

The 54 workers enter the session census. They do not enter a denominator for independent root runs. A current directory listing cannot enumerate deleted files. A current `progress.json` is a snapshot; it cannot reconstruct every state change. These counts do not set an operational target or support a causal claim about all post-cutover runs.
