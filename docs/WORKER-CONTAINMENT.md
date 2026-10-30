# Worker containment

`sandbox_workers` is on by default. Set it to `false` to turn it off.
The orchestrator stays outside the worker sandbox.

## When a worker cannot start

A graph implementation dispatch can stop with `containment_unavailable`,
`containment_gate_error`, or `containment_ack_required`. The Claude launcher can stop with
`branch_import_refused` or `worker_credential_missing`.

Run `python3 scripts/sandbox/containment.py [dir]` to see the mode and reason.
It also writes a `sandbox_launch/resolved/<code>` trace row. The modes are:

- `sandboxed`: the required runtime and credential are available.
- `fallback` with `sandbox_unavailable`: macOS needs `sandbox-exec` and `rg`;
  Linux needs `bwrap`. Both need `npx` and pinned srt in the npx cache.
  Prime the cache with `npx --yes @anthropic-ai/sandbox-runtime@0.0.65 --version`.
- `fallback` with `worker_credential_missing`: the owner must create
  `~/.coderails/worker_credential` with mode `0600`. The file must have one
  nonempty line: `ANTHROPIC_API_KEY=...` or `CLAUDE_CODE_OAUTH_TOKEN=...`.
  The owner can get the OAuth token with `claude setup-token`. A looser file
  mode or another variable name does not qualify.
- `fallback` with a `config_*` code: check that the config and schema can be
  read and have valid values. Graph implementation dispatch stops.
- `off` with `sandbox_workers_off`: containment was turned off explicitly.

Restore the sandbox runtime or credential before you dispatch the unit again.
Use `python3 scripts/sandbox/spawn_sandboxed_worker.py <worktree> <prompt_file> <model>`.
If the sandbox is ready, the owner can approve one in-process fallback with:

```sh
python3 scripts/action_receipt_cli.py approve-action --session <id> --kind worker_fallback --command 'worker_fallback <unit>' --cwd <worktree>
```

The signed receipt is single-use. It binds to the repository, branch, and HEAD.
Declare the unit `manifest` so a low-risk unit needs no approval.

## Trace and refusal codes

Read the trace with:

```sh
jq -r 'select(.command=="worker_containment" or .command=="sandbox_launch" or .command=="codex_worker") | [.command,.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl
```

- `containment_unavailable`: a sandbox prerequisite is missing. Graph dispatch stops.
- `containment_fallback_low_risk`: an in-process worker is allowed because its manifest avoids `HIGH_RISK_PREFIXES`.
- `containment_ack_required`: a high-risk in-process worker is denied.
- `containment_ack_receipt`: one owner receipt allowed the fallback.
- `containment_gate_error`: the hook could not verify a graph implementation
  dispatch and denied it. Check the error type in the trace row.
- `branch_import_refused`: a graph-owned manifest is missing, a commit is outside
  it, a commit contains a secret, another branch moved, or history was
  rewritten. No branch is imported or pushed. The clone stays under
  `$TMPDIR/sw.*/clone` for inspection.
- `branch_imported` and `branch_pushed`: the launcher completed those steps.

## Claude driver source transfer

For graph work, pass a new pristine feature checkout D through the existing
`graph.py drive --checkout` or `--checkout-map` interface. The root reserves D;
its tracked bytes, index and untracked state must match baseline H. The helper
does not allocate a different destination or import into an existing dirty tree.
It prepares a separate contained clone C before rendering and authorizing the
prompt. The prompt names C as execution checkout and D as root publication
checkout. The child receives the authorized stdin snapshot; the process receipt
still observes D's actual HEAD at exit.

After a successful admitted result, the root captures uncommitted proposed
source into private Git objects outside worker write scope. Capture never runs
worker Git, configuration, attributes, filters or index. Tracked H entries are
always considered. New untracked eligibility uses only trusted H ignore rules
in a root-owned context. Ignored directories may be pruned after checking the
entry; their contents are not inspected. Worker ignore changes cannot hide
out-of-scope proposed files. Scope, type, mode, path, dedicated credential and
known-secret checks run on the fixed proposal before destination writes.

Raw materialization preserves binary/new files/deletions without moving D's
HEAD or index. Root then reviews, tests, edits and publishes D through existing
gates. Resume validates the fixed receipt and never reapplies C over later root
edits. Nonzero/malformed/failed worker results cannot import successful output.
A drift or partial failure quarantines D; retain the journal and use the existing
failed-attempt path with a new pristine D. No reset, rollback or overwrite is
automatic. Historical unfinished Claude attempts cannot silently enter this route.

The attempt retains `workspace.json`, `capture.json`, `transfer-journal.json`
and `transfer.json`; additive hashes bind them to existing prepublication and
sealed driver evidence. `head_at_exit`, C, H, captured tree and root publication
HEAD remain distinct. Trace counters include `driver_workspace_prepared`,
`driver_source_materialized` and `driver_transfer_quarantined`.

Capture bounds: 10,000 visited entries, depth 64, 16 MiB per regular payload and
128 MiB total; private control-record reads are capped at 1 MiB. Refusal never
truncates source. Encoded or unknown secret formats may escape known-pattern
scanning. These are fixed untrusted observations, not a coherent terminal
filesystem snapshot. No stopped-descendant, genuine-provider or independent
same-user protection claim follows. Worker-reported tests may cover other bytes;
root verification must use the fixed proposed source.

## Codex workers

Codex native `spawn_agent` inherits the parent sandbox. While containment is on,
`loop_dispatch_guard.py` refuses a native implementation unit with
`codex_native_worker_uncontained`. Graph work uses the existing OAuth driver
through `graph.py cutover-driver` and `graph.py drive`; see
[driver recovery](RUNBOOK-DRIVER.md). Its authorization, immutable prompt,
terminal receipt, publication and sealed evidence checks govern completion.
A standalone successful process cannot supply that graph evidence.

The direct helper remains available for standalone work. It needs no API key
or second account and explicitly selects ChatGPT login with the OpenAI provider.
Launch it with:

```sh
python3 packages/codex/scripts/codex_worker.py --session <id> --checkout <feature-checkout> --prompt <file> --schema <checkout>/.coderails-worker/schema.json --output <checkout>/.coderails-worker/run.jsonl --final <checkout>/.coderails-worker/final.json
```

It records `codex_worker/starting/contained_process_start` before launch.
It then records `codex_worker/allowed/contained_process_complete`,
`codex_worker/failed/contained_process_failed`, or
`codex_worker/refused/contained_process_unavailable`. These standalone traces
are diagnostic and cannot complete an implementation unit. The graph driver
has its own issued-dispatch evidence path; it does not import these traces.
With `sandbox_workers: false`, native dispatch uses the parent's sandbox mode.

## Counters and limits

Run:

```sh
python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/containment_counters.py
PYTHONPATH=. python3 -m unittest hooks/scripts/tests/containment_test.py hooks/scripts/tests/worker_containment_gate_test.py
```

The output has a `containment` object. It counts `sandboxed`,
`sandbox_unavailable`, `worker_credential_missing`, and `sandbox_workers_off`
from launcher decisions. It counts `containment_unavailable`,
`containment_fallback_low_risk`, `containment_ack_required`,
`containment_ack_receipt`, `containment_gate_error`, and
`codex_native_worker_uncontained` from dispatch gates. It counts
`containment_gate_failed_open` only for traces from older builds. It counts
`branch_imported`, `branch_pushed`, and `branch_import_refused` from the Claude
launcher. It counts `contained_process_start`, `contained_process_complete`,
`contained_process_failed`, and `contained_process_unavailable` from Codex.

There is no real-loop baseline; all counters start at zero. One development
machine run took 0.15 seconds for `containment.py`. Pinned srt 0.0.65 was in
the npx cache, but no worker credential was present. The result was
`fallback / worker_credential_missing`. In a live srt probe, writes to
`~/.claude.json`, the primary `.git/refs/heads/main`, and the real HOME failed.
An in-scratch write succeeded. This is one measurement, not a benchmark.

If `sandboxed` is high and `branch_import_refused` is above zero, inspect
workers that touch branches they do not own. If `containment_ack_required`
dominates `containment_ack_receipt`, check high-risk in-process dispatch and
unit manifests. If `worker_credential_missing` dominates, provision the
credential before graph implementation work. Adding `containment_summary`
directly to `measure_graph_alignment.py` belongs to that file's owner.

This is a cooperating-agent safeguard, not absolute isolation. Claude can
read under the real HOME and reach `api.anthropic.com`; its trusted launcher
and the orchestrator are unsandboxed. GitHub egress is blocked in the Claude
worker. Codex `workspace-write` limits writes but shares the user OAuth location.
Its HOME, CODEX_HOME and TMPDIR follow the existing login environment; they are
not the isolated Claude scratch directories. Both Codex launchers allowlist
PATH, HOME, CODEX_HOME, TMPDIR, LANG, LC_ALL and TERM. Inherited API keys, tool
tokens, auth endpoint overrides and executable configuration variables are dropped.
Reads and same-user token access remain residuals.
An agent can edit `sandbox_workers`, a unit manifest, or the user-tier receipt
trust root. Synthetic OS probes do not prove a live Claude model session or
an accepted Codex graph dispatch.
