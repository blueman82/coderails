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
| `publication/refused/<code>` | the gate refused; `<code>` is `diff_manifest:<code>`, a review code, `pr_repo_override`, `pr_base_mutation`, or a later unit's code |

Manifest codes are `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`,
`special_file_type`, `mode_change`, `status_not_allowed`, `too_many_paths`, `manifest_unreadable` and
`manifest_internal_error`. `diff_manifest_mode_invalid` is a warning about forced enforcement, not a verdict code.
`foreign_session` belongs to the diagnostic CLI's explicit `--session` comparison. Publication checks unit owner-field
shape and worktree equality; it does not authenticate those owner fields.

## Counters

    python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py

prints `{command: {outcome/reason_code: count}}` for `diff-manifest`, `review-passes` and `publication`. Add a command name to
`COMMANDS` in that file when a unit adds a new row family; `measure_graph_alignment.py` is at its line limit and is not
edited.

## How to read it

- Healthy: `ok` rows dominate and `refused` rows are rare and each traceable to a real out-of-scope diff.
- Many `refused/manifest_unreadable`: check policy, diff, paired flags and requested unit metadata, including its manifest,
  owner fields and worktree. These rows do not identify an out-of-scope path.
- Any `refused/manifest_internal_error`: a bug in the gate; file it.
- `warned` rows with no `refused` rows mean the install is on `advisory` (the pre-default behaviour).
- No `publication/*` rows at all proves nothing: it is also what a disabled hook, an untrusted Codex plugin or
  `diff_manifest: off` look like. Push emits `diff-manifest` rows without `publication` rows. Confirm active registration
  and observe a denial through the relevant installed consumer before claiming installed enforcement.

## Limits

The rows are written by the same user that the gate constrains and never decide anything. They measure how often the
gate fired, not whether publication paths exist that bypass it (a merge made from a browser or a script the Codex hook
cannot match is invisible). The gate is a cooperating-agent safeguard: an agent with write access to
`.coderails/workflow.config.yaml` can set `diff_manifest: off`, and that change is itself a diff the gate reviews only if
the policy denies the path. The shipped policy denies additions or modifications to its own policy paths and workflow
config, but it reads the local checkout's effective config. A same-worktree progress file with forged nonblank owner
fields can pass the metadata check. Claude's direct manifest arm runs without config or a transcript; raw Git operations,
unmatched scripts/aliases and browser merges are not observations of this publication gate. Direct hooks cannot pin
the subsequent remote merge head or base; `merge.py` uses `--match-head-commit` for the head. Trace-write failure is ignored, so missing rows
also cannot prove that a check did not run.
