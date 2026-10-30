# Local graph driver recovery

## A local graph worker paused

- Run `graph.py inspect <progress.json>` before you act. Finish an active native wave with its supported command. Then
  `graph.py cutover-driver <progress.json> --session <id>` can make a one-way driver cutover. It saves
  `<progress.json>.pre-driver`; keep both files. The driver records process results, not native `spawn_agent` evidence.
- Run `graph.py drive <progress.json> --session <id> --checkout <worker-checkout>` in the foreground. Use
  `--checkout-map <json-file>` when workers need separate retained checkouts. Codex uses the current Codex OAuth login
  through `codex exec` with `forced_login_method="chatgpt"` and the OpenAI provider.
  Both launch routes remove inherited API credentials and auth endpoint overrides. A missing OAuth login fails;
  there is no API-key or Claude fallback. Ordinary workers use Codex's `workspace-write` sandbox. Guarded roles
  use a separate `read-only` session with their role's capability server; raw shell and nested agents are disabled.
- `drive` waits at most 30 seconds by default. Set `--wait-seconds <0..3600>` to change that wait. A `running` result
  with `reason: wait_limit` names the retained `attempt` directory and `dispatch_id`; it does not stop the worker.
  Inspect `launch.json`, `heartbeat.json`, `stderr.log`, `output.jsonl`, and, when present, `terminal.json` there.
  For a Claude worker, its sandbox launcher also names a separate `worker.stderr.log` in its scratch directory.
  Keep JSONL output separate from stderr. Run the same `drive` command again to observe a finished attempt.
- `active_missing_task` means a pending unit needs a task. Use `graph.py assign-unit-scope` while no wave is active, then
  run `drive` again. A root-owned step pauses for `graph.py record-driver-control` with a retained result file.
- `publication_required` means the worker left source changes for the root to review and publish. The controller checks
  that the checkout is clean and its exact HEAD belongs to an open PR before it records the work as done. Review, tests,
  evaluation and the integrity check still govern merge.
- After an interruption, run `drive` again with the retained checkout. A missing or stale worker heartbeat is
  `unresolved`; inspect the saved attempt files and wrapper PID before any recovery. The launch reservation blocks a
  second worker for that attempt. If the wrapper died, keep the attempt and report the unresolved graph state for
  operator review. The driver has no automatic kill, retry, or replacement operation for that attempt.

The controller captures one UTF-8 prompt byte snapshot before authorization. The authorization command still checks
the owned prompt file. The controller compares the snapshot hash with the authorized digest before starting the child.
Ordinary and guarded children consume that snapshot through stdin. A later change or removal of the file cannot replace
the child's input. A digest mismatch refuses launch. Existing sealed evidence still requires its original artifacts.

Codex refusals append advisory rows to `recovery-trace.jsonl` beside the graph. `driver_launch_refused` identifies
setup or launch failure, `driver_prompt_digest_mismatch` identifies a snapshot that differs from its authorized hash,
and `driver_authorization_refused` identifies an invalid or consumed dispatch. A refusal does not record completion.
Read `stderr.log` for the child process error. An advisory trace never grants authorization or repairs graph evidence.

The OAuth selector is supported by Codex CLI 0.165.0 and documented in the
[OpenAI authentication reference](https://learn.chatgpt.com/docs/auth#enforce-a-login-method-or-workspace).
Synthetic child probes establish source routing and credential filtering. They do not establish real OAuth login,
native model execution, a genuine publication, or full-loop acceptance.

The worker wrapper records `head_at_exit` in its existing `terminal.json` receipt after the child ends and before
publishing that receipt atomically. The receipt token must match the launch record, and its exit code must match the
worker result. The prepublication exit HEAD must match the receipt. The later manifest records the published checkout
HEAD separately. A root commit after the child exits does not change
the recorded exit HEAD. Before the manifest exists, equivalent JSON formatting is accepted; bound facts must match.
After the manifest exists, its raw seal hash also detects representation changes.

Before upgrading, finish pending publication with the runtime that created the attempt and retain its qualification
limits and artifacts. A historical terminal receipt without a valid exit HEAD cannot prove that provenance. This version
refuses its prepublication qualification. It does not backfill the field from the current checkout or select an older
runtime automatically. Other retained paths that do not require prepublication provenance keep their existing checks.
The receipt and seal are same-user evidence. Matching fields detect one-sided changes, not coordinated forgery.
