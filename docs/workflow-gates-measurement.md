# Workflow gates: measurement note

What is measured for the publication gate (`scripts/lib/publication_gate.py`) and the diff manifest it runs, how to read
it, and what the numbers cannot tell you.

## Rows

Every refusal writes non-authoritative trace rows (`<loop dir>/<session>/trace.jsonl`; the session id is
`<repo>@pr-<N>` or `<repo>@<branch>`), tallied by `measure_graph_alignment.py` into `trace.by_reason` keyed
`command/outcome/reason_code`:

| Row | Meaning |
|---|---|
| `diff-manifest/ok/diff_manifest_ok` | a diff passed the policy |
| `diff-manifest/refused/<code>` | enforce refused for `<code>` (one row per violation) |
| `diff-manifest/warned/<code>` | advisory saw a violation and let it through |
| `diff-manifest/failed_open/<manifest_unreadable\|manifest_internal_error>` | advisory could not evaluate |
| `diff-manifest/legacy/manifest_legacy_absent` | the policy has no `manifest` key |
| `diff-manifest/warned/diff_manifest_mode_invalid` | an unknown `diff_manifest` value was treated as enforce |
| `publication/refused/<code>` | the single gate refused; `<code>` is `diff_manifest:<code>`, and later units add theirs |

## Counters

    python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py

prints `{command: {outcome/reason_code: count}}` for `diff-manifest` and `publication`. Add a command name to
`COMMANDS` in that file when a unit adds a new row family; `measure_graph_alignment.py` is at its line limit and is not
edited.

## How to read it

- Healthy: `ok` rows dominate and `refused` rows are rare and each traceable to a real out-of-scope diff.
- Many `refused/manifest_unreadable`: a policy path or the PR head cannot be read (fix the path), not a policy hit.
- Any `refused/manifest_internal_error`: a bug in the gate; file it.
- `warned` rows with no `refused` rows mean the install is on `advisory` (the pre-default behaviour).
- No `publication/*` rows at all proves nothing: it is also what a disabled hook, an untrusted Codex plugin or
  `diff_manifest: off` look like. Confirm by observing one real denial after a restart (a throwaway PR with a symlink).

## Limits

The rows are written by the same user that the gate constrains and never decide anything. They measure how often the
gate fired, not whether publication paths exist that bypass it (a merge made from a browser or a script the Codex hook
cannot match is invisible). The gate is a cooperating-agent safeguard: an agent with write access to
`.coderails/workflow.config.yaml` can set `diff_manifest: off`, and that change is itself a diff the gate reviews only if
the policy denies the path.
