# Workflow gates: measurement note

What is measured for the publication gate (`scripts/lib/publication_gate.py`) and the diff manifest it runs, how to read
it, and what the numbers cannot tell you.

## Rows

Every refusal writes non-authoritative trace rows (`<loop dir>/<session>/trace.jsonl`; the session id is
the sanitized `<repo>@pr-<N>` or `<repo>@<branch>` label (falling back to `pr-<N>`/`local` when metadata fails),
tallied by `measure_graph_alignment.py` into `trace.by_reason` keyed
`command/outcome/reason_code`:

| Row | Meaning |
|---|---|
| `diff-manifest/ok/diff_manifest_ok` | a diff passed the policy |
| `diff-manifest/refused/<code>` | enforce refused for `<code>` (one row per violation) |
| `diff-manifest/warned/<code>` | advisory saw a violation and let it through |
| `diff-manifest/failed_open/<manifest_unreadable\|manifest_internal_error>` | advisory could not evaluate |
| `diff-manifest/legacy/manifest_legacy_absent` | the policy has no `manifest` key |
| `diff-manifest/warned/diff_manifest_mode_invalid` | an unknown `diff_manifest` value was treated as enforce |
| `review-passes/ok/review_passes_ok` | the artifact's passes covered every pass the diff requires |
| `review-passes/refused/<code>` | `<code>` is `required_review_missing:<name>`, `required_review_failed:<name>`, `review_passes_malformed`, `review_artifact_missing` or `review_policy_unreadable` |
| `eval-level/ok/eval_level_ok` | the selected suite named the current PR head and every P0 passed, its level covered the live diff and declared/posted work-unit floor, the late-freeze stamp matched, and the suite verified with a full frozen SHA at level 1 or 2 |
| `eval-level/refused/<code>` | `<code>` is `level_below_derived`, `late_freeze_unstamped`, `suite_hash_mismatch`, `suite_hash_marker_mismatch`, `chain_broken`, `chain_truncated`, `integrity_stripped`, `not_frozen`, `eval_facts_missing`, `eval_artifact_missing`, `eval_artifact_unreadable`, `eval_embed_malformed`, `eval_head_mismatch`, `eval_result_mismatch` or `eval_level_diff_unavailable` |
| `publication/refused/<code>` | the single gate refused; `<code>` is `diff_manifest:<code>`, a review code or an eval-level code |
| `routine/<outcome>/<code>` | a routine event from `scripts/routine_log.py`: `<outcome>` is `stage_ok`, `run_ok`, `run_abort`, `run_refused` or `run_incomplete`; `<code>` is the closed per-routine reason code (`none` for `stage_ok`/`run_ok`), e.g. `routine/run_abort/docs_sync_deny`, `routine/run_refused/merge`, `routine/run_incomplete/incomplete-run`; keyed by the routine name as session id |
| `verify-merged/ok/verified` | `scripts/verify_merged.py` confirmed a PR landed (by content, or by merge-commit ancestry) |
| `verify-merged/refused/<code>` | `<code>` is the first reason: `gh_failed`, `not_merged`, `merged_at_missing`, `fetch_failed`, `merge_commit_unreachable`, `content_absent` or `content_check_required` (keyed `<repo>@pr-<N>`) |
| `argv/denied/ceiling_exceeded` | the verification-volume ceiling denied a 3rd+ full suite or `post_evals.py post\|validate-structure` in one worktree (keyed by the session that ran it) |
| `argv/denied/protected_paths_unreadable` | `policy/protected_paths.json` was missing or ill-shaped and an edit on main was refused (fail closed) |

Manifest codes are `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`,
`special_file_type`, `mode_change`, `status_not_allowed`, `too_many_paths`, `manifest_unreadable` and
`manifest_internal_error`. `diff_manifest_mode_invalid` is a warning about forced enforcement, not a verdict code.
`foreign_session` belongs to the diagnostic CLI's explicit `--session` comparison. Publication checks unit owner-field
shape and worktree equality; it does not authenticate those owner fields.

Routine counters count emitted events, not unique completed jobs. `run_incomplete` is provisional; explicit
`begin --new` closes an open previous id with `run_abort/incomplete-run`. An unspawnable gate emits
`run_refused/<gate>`. A failed log write (`log_unwritable`) or foreign state (`routine_mismatch`) is reported on stderr
without a success trace or state advancement. Partial file writes and the runner's unlocked fallback appends are not
transactional or authoritative counter evidence; inspect JSONL, human log and state together.

## Counters

    python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py

prints `{command: {outcome/reason_code: count}}` for `diff-manifest`, `review-passes`, `eval-level`, `publication`, `argv`, `routine` and `verify-merged`. Add a command name to
`COMMANDS` in that file when a unit adds a new row family; `measure_graph_alignment.py` is at its line limit and is not
edited.

## How to read it

- Healthy: `ok` rows dominate and `refused` rows are rare and each traceable to a real out-of-scope diff.
- Many `refused/manifest_unreadable`: check policy, diff, paired flags and requested unit metadata, including its manifest,
  owner fields and worktree. These rows do not identify an out-of-scope path.
- Any `refused/manifest_internal_error`: a bug in the gate; file it.
- `refused/eval_head_mismatch` means the selected suite omits or disagrees with the current PR head;
  `refused/eval_result_mismatch` means a GO artifact contains a P0 that did not pass. Correct the head/evidence,
  rerun and regrade the evals, then re-post with `post_evals.py post <PR> <evals.json>`. These use the existing
  `eval-level/refused/<code>` and `publication/refused/<code>` rows and counters.
- `warned` rows with no `refused` rows mean the install is on `advisory` (the pre-default behaviour).
- No `publication/*` rows at all proves nothing: it is also what a disabled hook, an untrusted Codex plugin or
  `diff_manifest: off` look like. Push emits `diff-manifest` rows without `publication` rows. Confirm active registration
  and observe a denial through the relevant installed consumer before claiming installed enforcement.

### Argv rows

- `argv/denied/ceiling_exceeded` should be rare and each traceable to a loop that re-ran a full suite. The count files
  (`<loop dir>/verification-ceiling/<sha1>__<target>.count`, Codex `$PLUGIN_DATA/verification-ceiling/`) are the
  authority, the trace rows only tally denials. Optional `work_units[u].verification{run_all,post_evals}` mirrors require
  an exact payload session and existing `CLAUDE_LOOP_ID`, schema-3 in-progress state, one physical worktree match and
  its running `U3[<id>]` registration in `active_wave.nodes`. A skipped mirror does not change the ceiling decision.
  Native producer worktree registration is a separate dependency; supplied fixtures do not prove installed integration.
- Any `argv/denied/protected_paths_unreadable` means `policy/protected_paths.json` is broken in the installed plugin:
  edits on main are refused until it is repaired. Commit, push and merge recognition rows are not written; a drop in
  gated commits after the classifier shipped cannot be told apart from fewer commits.

### Procedure scripts

`verify_merged.py` is the only one of the prose-to-script helpers that writes rows. `wiki_lint.py stale`, `memory_dir.py`,
`detect_test_command.py`, `merge.py --describe` and `check.py --json` are read-only and print their result (`memory_dir.py`
prints a path; the others print JSON); they
write no trace rows, so there is no count of how often a skill ran them. A rising `verify-merged/refused/content_absent`
or `content_check_required` means claims of "merged" are not being backed by content (or the skill is called without
`--grep` on squash merges), not that merges are failing.
`content_preexisting` means the needle predates the merge; `content_check_failed` means Git could not establish presence
or absence (for example, a shallow clone lacks the first parent). Neither is a merge-failure count. Restore history or
choose a new needle before retrying. Wiki candidate/data-gap counts and quality feedback are advisory output, not
installed-call or enforcement measurements; the Codex quality adapter attempts no external tools.

## Limits

The rows are written by the same user that the gate constrains and never decide anything. They measure how often the
gate fired, not whether publication paths exist that bypass it (a merge made from a browser or a script the Codex hook
cannot match is invisible). The gate is a cooperating-agent safeguard: an agent with write access to
`.coderails/workflow.config.yaml` can set `diff_manifest: off`, and that change is itself a diff the gate reviews only if
the policy denies the path. The shipped policy denies additions or modifications to its own policy paths and workflow
config, but it reads the local checkout's effective config. A same-worktree progress file with forged nonblank owner
fields can pass the metadata check. Claude's direct arm needs config and a readable transcript; raw Git operations,
unmatched scripts/aliases and browser merges are not observations of this publication gate. Direct hooks cannot pin
the subsequent remote merge head; `merge.py` uses `--match-head-commit`. Trace-write failure is ignored, so missing rows
also cannot prove that a check did not run.
