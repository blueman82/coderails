# Post-cutover run observability baseline

## Validation checklist

- [x] Freeze the UTC window and providers before the count. Specify what counts as a native session and what to skip.
- [x] Give each metric its rule, numerator, denominator, rate, source, method, and basis.
  Use `unavailable` if no one did the necessary audit independently.
- [x] Count `work_units` and graph nodes on their own. The `eval_refs` values identify evals and do not map the two counts.
- [x] Count frozen loop cost, transcript token use, and active engineering minutes on their own.
- [x] Check each positive claim against a native artifact or the two post-cutover commits. Set no target for operation.

## Frozen cohort and inventory

**Window:** From 2026-09-28 11:32:24 UTC (cutover merge `e1090098`) through **2026-09-28 22:51:05 UTC** (census freeze), with the two endpoints included.
**Providers:** Native Claude Code and native Codex.
The cohort uses native session start time and a Coderails repository working directory.
Each worker counts as one native session apart from its parent. A loop does not count as a session.

The census skips entries after the cutoff, This includes entries for sessions that started in the window.
It counts sessions that start in the window. It does not count all sessions that were active during the window.

| Native source | Candidate files | Included sessions | Exclusions | Basis |
| --- | ---: | ---: | --- | --- |
| Codex `~/.codex/sessions/2026/09/28/*.jsonl` | 81 | 56: 2 roots, 54 workers | 5 began before cutover, 17 used other working directories, and 3 used Coderails wiki directories. | The first record of each file gave `session_meta.payload.id`, `timestamp`, `cwd`, and `parent_thread_id`. All 54 workers in the cohort name a parent in the cohort. |
| Claude `~/.claude/projects/**/*jsonl` with `coderails` in its path | 632 | 0 | 630 began before cutover. Two have no usable record with `sessionId` and `cwd`. | The census used the first record with `sessionId`, `cwd`, and `timestamp` in each file with a matching path. It did not count the two unresolved files as clean sessions. |
| **Total** | **713** | **56** | **657** | Sum of the two native inventories. |

The directory rule accepts `/Users/harrison/Github/coderails` and its Coderails worktrees. It skips `/Users/harrison/Github/coderails-wiki`.
The two Codex roots are `01a0e7ed-3515-7e73-a760-cfb2bd8c4763` (12:11:17 UTC) and `01a0ea0d-1a4e-7480-98b5-a1e7931a13a2` (22:05:22 UTC).
Their native rollout files are in the Codex source directory above.
The second root had not finished at the census and cannot count in an audit of completed results.

A subsequent Codex rollout started at 22:55:37 UTC, after the cutoff. The directory has 82 files and the cutoff inventory has 81.
The counts use local artifacts. The census has no records for deleted historical sessions.
No source manifest counts deleted files, so that exclusion count is unavailable.

## Metric record, version 1

The `N/D` ratio uses the counted numerator and the eligible audited denominator.
`Unavailable` means there is no necessary record or no audit that someone ran independently. It does not mean 0.
Calculate rates only when records give the two counts. All rows use the frozen cohort above.
Use the paths and IDs below to find the native records.

| Metric and counting rule | N / D and rate | Basis and method | Records and exclusions |
| --- | --- | --- | --- |
| **Divergence between loop records.** Count incorrect declared work-unit and node pairs for each declared pair that someone inspects independently. | Unavailable / 0. Rate unavailable. | The inspected snapshots gave no declared pair. A divergence audit uses declared pairs only. | See the root graph data below. The relationship inventory skips other sessions without an inspected graph. |
| **Duplicate mutation.** Count retries that an audit confirms did the same accepted change to the same target. The denominator is mutation sequences that someone audits independently. Skip rejected calls and retries necessary to finish a change. | Unavailable / 0. Rate unavailable. | A manual incident audit is necessary. A transcript command or current graph snapshot cannot prove a repeat of an accepted change. | The native rollout files and `progress.json` snapshots give no incident record or mutation sequence audit that someone ran independently. None of the 56 sessions has this audit. |
| **Repair incidents.** Count repair episodes that someone groups independently for each root session they examine independently for repair history. Count one episode when it has multiple commands. | Unavailable / 0. Rate unavailable. | No one audited and grouped root repair history independently. Candidate R1 below does not count. | See the candidate records below. No one checked the second root or 54 child sessions independently for individual repair episodes. |
| **Incorrect blocks at loop end.** Count block conditions that someone disproves by replaying the artifacts independently. The denominator is blocks that the replay checks against the same source artifacts. | Unavailable / 0. Rate unavailable. | No one replayed a gate independently against the same artifacts. | The first root's `GO` in `evals.json` and `complete` in `progress.json` are provider records. The active second root does not count in this audit. |
| **Incorrect results that permit loop end.** Count results that someone checks independently and shows violated a mandatory condition. The denominator is the results that such an audit checks. | Unavailable / 0. Rate unavailable. | No one replayed all mandatory conditions independently against the same native transcript, proof, eval, and retro artifacts. | First root's `progress.json`, `evals.json`, `proof.json`, and `retro.json`. The second root was active. A provider's result cannot count as its own audit. |
| **Adapter and test duplication.** Count provider-specific tests of the same behavior for each shared semantic change that someone checks independently across providers. | Unavailable / 0. Rate unavailable. | Commit file counts are below. No one compared the behavior that the tests exercise. The metric skips mandatory provider-native record handling. | `git show --numstat cdf6bdf1 a275153d`. The census skips uncommitted provider work because its change boundary was not frozen. |
| **Updates to the two loop views.** Count audited items that need manual updates in `work_units` and graph nodes for the same decision. The denominator is items where the owner explicitly assigned the same decision to the two views. | Unavailable / 0. Rate unavailable. | There is no owner-declared pairing or audit of each operation. Equal snapshot counts cannot show duplicate updates. | The two root `progress.json` snapshots above. The count skips unpaired entries and other sessions. |
| **Maintenance time.** Count recorded active engineering minutes by category for each graph change with a manual task-time record from that time. | Unavailable / 0. Rate unavailable. | No task-time record gives active minutes for the shared kernel, Claude adapter, Codex adapter, tests, or repair. | The commits `cdf6bdf1` and `a275153d`, worker report, and retros record work and checks without minutes. Transcript token use and frozen `retro.cost` do not give minutes. |

### Root graph data

The first root's current `~/.coderails/agentic-loop/-Users-harrison-Github-coderails-.git/01a0e7ed-3515-7e73-a760-cfb2bd8c4763/progress.json` has 1 `work_units` entry and 1 graph node.
The snapshot cannot show the counts at the census time.
The second root's frozen `evals.json` (22:09:49 UTC) describes seven dependent work units. Its current `progress.json` has 7 `work_units` entries.

The second graph changed after the census. There is no durable record of the node count at the census, so it is unavailable.
The work units and nodes are different inventories. The `eval_refs` values do not pair them.

### Documented repair candidate and duplication footprint

Candidate R1 belongs to root `01a0e7ed-3515-7e73-a760-cfb2bd8c4763`.
The worker report groups two corrections in one unit, for active-wave identity and Codex data-write defects.
It gives the causes of hard-stop and invalid-proposal, the before and after regression checks, and repair commit `cdf6bdf1`.

The sources are `/private/tmp/coderails-post-cutover-state-worker-report.md`, `git show cdf6bdf1`, and the archived `01a0e7ed-3515-7e73-a760-cfb2bd8c4763-completed-post-cutover-state-defects-20260928-01/retro.json`.
The retro is in the loop root above. It records the same repair scope.
The records describe repair work but cannot establish incident history or the denominator independently.

The same root subsequently had a stranded fixture loop and recovery.
No one grouped the episodes for this root independently. This report gives no positive numerator or rate.

For the committed shared semantics change `cdf6bdf1`, the diff adds **5 lines and removes 7 lines** in `packages/graph-semantics/graph_semantics.py` and each provider copy.
It also adds 41 lines in `packages/tests/test_provider_graph_lifecycle.py`, 16 in `packages/tests/test_codex_graph_runtime.py`, and 2 in the Codex graph adapter.
The subsequent fixture commit `a275153d` adds 38 one-line shared fixtures in `packages/graph-semantics/fixtures/`.
That committed diff adds no provider-specific tests.

These file and line counts cover two commits. They cannot give a duplicate-case rate.
The audit did not compare the behavior that the tests exercise or find a task-time record for adapter maintenance.

## Coverage and audit limits

The census uses readable local native files and the frozen start window.
Metric denominators can be smaller because the metrics use audits that someone did independently.
The first completed root has one documented repair candidate without such an audit. The other root was active at the cutoff.
The repair metric has 0 roots that someone audited independently.

The census includes 54 workers. The root-run denominator does not count them.
A current directory listing cannot count missing or deleted files. A current `progress.json` snapshot cannot reconstruct all changes to loop data.
These counts give no target for operation or causal claim about all post-cutover runs.
