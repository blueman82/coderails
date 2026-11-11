# Worker containment

`sandbox_workers` is on by default. Set it to `false` to turn it off.
The orchestrator does not use the worker sandbox.

## When a worker cannot start

A graph implementation dispatch can stop with `containment_unavailable`,
`containment_gate_error`, or `containment_ack_required`. The Claude launcher can stop with
`branch_import_refused` or `worker_credential_missing`.

Run `python3 scripts/sandbox/containment.py [dir]` to see the mode and cause.
It also writes a `sandbox_launch/resolved/<code>` diagnostic log entry.

- `sandboxed`: The runtime and credential are available.

- `fallback` with `sandbox_unavailable`: On macOS, the sandbox uses `sandbox-exec` and `rg`. On Linux, it uses `bwrap`.
  The two systems also use `npx` and pinned srt in the npx cache.
  Fill the cache with `npx --yes @anthropic-ai/sandbox-runtime@0.0.65 --version`.

- `fallback` with `worker_credential_missing`: The owner must make `~/.coderails/worker_credential` with mode `0600`.
  The file must have one nonempty line: `ANTHROPIC_API_KEY=...` or `CLAUDE_CODE_OAUTH_TOKEN=...`.
  The owner can get the OAuth token with `claude setup-token`. The check refuses a less strict file mode or a different credential name.

- `fallback` with a `config_*` code: Check that the config and schema are readable and have correct values.
  The gate stops graph implementation work.

- `off` with `sandbox_workers_off`: The config turns containment off explicitly.

Put back the sandbox runtime or credential before you try to start the unit again.
Use `python3 scripts/sandbox/spawn_sandboxed_worker.py <worktree> <prompt_file> <model>`.
If the sandbox can run, the owner can give approval for one in-process fallback with:

```sh
python3 scripts/action_receipt_cli.py approve-action --session <id> --kind worker_fallback --command 'worker_fallback <unit>' --cwd <worktree>
```

The signed receipt is single-use. It identifies the repository, branch, and HEAD.
Declare the unit `manifest` so the gate can accept a low-risk unit without approval.

## Trace and refusal codes

Read the diagnostic log with:

```sh
jq -r 'select(.command=="worker_containment" or .command=="sandbox_launch" or .command=="codex_worker") | [.command,.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl
```

- `containment_unavailable`: A sandbox prerequisite is unavailable. The gate stops graph dispatch.
- `containment_fallback_low_risk`: The gate accepts an in-process worker if its manifest avoids `HIGH_RISK_PREFIXES`.
- `containment_ack_required`: The gate denies a high-risk in-process worker.
- `containment_ack_receipt`: One owner receipt gave approval for fallback.
- `containment_gate_error`: The hook could not check the graph implementation dispatch and denied it. Check the error type in the diagnostic log entry.
- `branch_import_refused`: The launcher refuses if it cannot find a graph-owned manifest. It refuses a commit with a secret or a path external to the manifest scope.
  It also refuses if a different branch moved or the worker rewrote history. The launcher does not import or push a branch.
  The clone stays in `$TMPDIR/sw.*/clone` for inspection.
- `branch_imported` and `branch_pushed`: The launcher completed those steps.

## Claude driver source transfer

For graph work, give `graph.py drive --checkout` or `--checkout-map` a new pristine feature checkout D.
The root reserves D. Its tracked bytes, index, and untracked contents must agree with baseline H.
The helper uses only D as the destination and refuses a dirty tree.

The helper prepares an isolated clone C before it builds the prompt and gets authorization.
The prompt names C for execution and D for root publication. The child gets the stdin snapshot from the authorization.
The receipt records D's actual HEAD at exit.

After the root accepts a result that shows success, it captures the proposed uncommitted source in private Git objects.
The worker cannot write to those objects. Capture does not use the worker's Git, configuration, attributes, filters, or index.
It includes tracked H entries in its checks. It uses only trusted H ignore rules in a root-owned context to classify new untracked paths.

Capture may prune an ignored directory after it checks the entry. It does not read that directory's contents.
The worker cannot hide proposed files external to the scope by changing ignore rules.
Before writing to D, capture checks the fixed proposal's scope, type, mode, path, dedicated credential, and known secrets.

Raw materialization keeps binary and new files and deletions without moving D's HEAD or index.
The root examines, tests, edits, and publishes D through the publication gates.
On resume, the controller checks the fixed receipt. It does not apply C again after subsequent root edits.
The controller cannot import a result as success if the worker exits nonzero, gives malformed data, or reports an error.

The controller quarantines D if it changes unexpectedly or if a write stops before the source copy ends.
Keep the journal. Use the path for an unsuccessful run with a new pristine D.
The controller does not set D to its previous contents, roll it back, or overwrite it automatically.
It does not let unfinished historical Claude runs enter this path silently.

The run keeps `workspace.json`, `capture.json`, `transfer-journal.json`, and `transfer.json`.
More hashes bind these files to the prepublication and sealed driver records.
The `head_at_exit`, C, H, captured tree, and root publication HEAD identify different facts.
Diagnostic counters include `driver_workspace_prepared`, `driver_source_materialized`, and `driver_transfer_quarantined`.

Capture limits: 10,000 entries, depth 64, 16 MiB for each regular payload, and 128 MiB total.
Reads of private control records have a 1 MiB limit. A refusal does not truncate source.
The scan may miss encoded secrets and formats it does not know.

These records contain fixed observations of untrusted data. They do not prove a coherent terminal filesystem snapshot.
They do not prove that descendants stopped, that a live provider ran, or that the same user cannot change data.
The worker may have tested different bytes. The root must check the fixed proposed source.

## Codex workers

Codex native `spawn_agent` inherits the parent sandbox. While containment is on, `loop_dispatch_guard.py` refuses native implementation work.
The refusal code is `codex_native_worker_uncontained`.
Use the OAuth driver through `graph.py cutover-driver` and `graph.py drive`. See [driver recovery](RUNBOOK-DRIVER.md).

The checks for the end of graph work use the authorization, immutable prompt, terminal receipt, publication, and sealed records.
A standalone worker result cannot supply those graph records.

The direct helper remains available for standalone work. No API key or second account is necessary. It explicitly selects ChatGPT login with the OpenAI provider.
Launch it with:

```sh
python3 packages/codex/scripts/codex_worker.py --session <id> --checkout <feature-checkout> --prompt <file> --schema <checkout>/.coderails-worker/schema.json --output <checkout>/.coderails-worker/run.jsonl --final <checkout>/.coderails-worker/final.json
```

It records `codex_worker/starting/contained_process_start` before launch.
It then records `codex_worker/allowed/contained_process_complete`, `codex_worker/failed/contained_process_failed`, or `codex_worker/refused/contained_process_unavailable`.
These standalone log entries are diagnostic. They cannot complete an implementation unit.

The graph driver uses its own dispatch records. It does not import these entries.
With `sandbox_workers: false`, native dispatch uses the parent's sandbox mode.

## Counters and limits

Run:

```sh
python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/containment_counters.py
PYTHONPATH=. python3 -m unittest hooks/scripts/tests/containment_test.py hooks/scripts/tests/worker_containment_gate_test.py
```

The output has a `containment` object. It counts `sandboxed`, `sandbox_unavailable`, `worker_credential_missing`, and `sandbox_workers_off` from launcher decisions.
For dispatch gates, it counts `containment_unavailable`, `containment_fallback_low_risk`, `containment_ack_required`, `containment_ack_receipt`, `containment_gate_error`, and `codex_native_worker_uncontained`.
It counts `containment_gate_failed_open` only for logs from previous builds.

For the Claude launcher, it counts `branch_imported`, `branch_pushed`, and `branch_import_refused`.
For Codex, it counts `contained_process_start`, `contained_process_complete`, `contained_process_failed`, and `contained_process_unavailable`.

All counters start at zero. There is no baseline from a live loop.
One development machine ran `containment.py` in 0.15 seconds. The npx cache had pinned srt 0.0.65. The machine had no worker credential.
The result was `fallback / worker_credential_missing`.

In a live srt test, the sandbox blocked writes to `~/.claude.json`, the primary `.git/refs/heads/main`, and the user's `HOME`.
A write to the scratch directory succeeded. This is one measurement.

If `sandboxed` is high and `branch_import_refused` is above zero, examine workers that touch branches they do not own.
If `containment_ack_required` is greater than `containment_ack_receipt`, check high-risk in-process dispatch and unit manifests.
If `worker_credential_missing` dominates, set the credential before graph implementation work.
The file owner can add `containment_summary` directly to `measure_graph_alignment.py`.

This is a cooperating-agent safeguard. Claude workers can read from the user's `HOME` and connect to `api.anthropic.com`.
The trusted launcher and orchestrator do not use the sandbox. The Claude worker cannot connect to GitHub.

Codex `workspace-write` limits writes and shares the user's OAuth location.
HOME, CODEX_HOME, and TMPDIR come from the login environment. The isolated Claude scratch directories do not apply.
The two Codex launchers use an allowlist: PATH, HOME, CODEX_HOME, TMPDIR, LANG, LC_ALL, and TERM.
They drop inherited API keys, tool tokens, auth endpoint overrides, and executable configuration settings.
Reads and access to tokens by the same user remain possible.

An agent can edit `sandbox_workers`, a unit manifest, or the user-tier receipt trust root.
Synthetic OS tests do not prove that a live Claude model session ran or that Codex accepted a graph dispatch.
