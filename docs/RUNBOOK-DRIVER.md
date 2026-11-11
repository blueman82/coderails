# Local graph driver recovery

## A local graph worker paused

- Run `graph.py inspect <progress.json>` first. If a native wave is active, finish it with its command.
  Then run `graph.py cutover-driver <progress.json> --session <id>` to select the driver permanently.
  It writes `<progress.json>.pre-driver`. Keep the two files. The driver records the results of the child. It does not make native `spawn_agent` records.

- Run `graph.py drive <progress.json> --session <id> --checkout <worker-checkout>` in the foreground.
  Use `--checkout-map <json-file>` if workers need their own saved checkouts.
  Codex uses the current Codex OAuth login through `codex exec` with `forced_login_method="chatgpt"` and the OpenAI provider.

  The two launch paths remove inherited API credentials and auth endpoint overrides. If there is no OAuth login, the launch fails.
  There is no API-key or Claude fallback. Usual workers use the Codex `workspace-write` sandbox.
  Roles with tighter controls use their own `read-only` sessions with the tool server for that role.
  These sessions disable raw shell and nested agents.

- By default, `drive` waits 30 seconds or less. Set `--wait-seconds <0..3600>` to change the wait.
  A `running` result with `reason: wait_limit` names the saved `attempt` directory and `dispatch_id`. It does not stop the worker.
  Examine `launch.json`, `heartbeat.json`, `stderr.log`, and `output.jsonl` there. Read `terminal.json` if the worker wrote it.

  For a Claude worker, the sandbox launcher also names a `worker.stderr.log` in its scratch directory.
  Keep JSONL output and stderr in different files. Run the same `drive` command again to check the outcome after the worker ends.

- `active_missing_task` means a pending unit needs a task.
  Use `graph.py assign-unit-scope` while no wave is active. Then run `drive` again.
  A root-owned step pauses for `graph.py record-driver-control` with a saved result file.

- `publication_required` means the worker has source changes for the root to examine and publish.
  The controller checks that the checkout is clean and its head belongs to an open PR before it records the work as done.
  The inspection, tests, eval, and integrity check continue to control merge.

- After an interruption, run `drive` again with the saved checkout.
  A missing or stale worker heartbeat gives `unresolved`. Examine the saved files for that run and the wrapper PID before you try to start the work again.
  The launch reservation blocks a second worker for the same run.
  If the wrapper died, keep its files and report the unresolved graph data for the operator to examine.
  The driver cannot automatically kill, retry, or replace that run.

The controller captures one snapshot of the UTF-8 prompt bytes before authorization. The authorization command continues to check the owned prompt file.
The controller compares the snapshot hash with the digest in the authorization before it starts the child.

Usual children and those with tighter controls read the snapshot through stdin. Changes to the file after capture cannot replace the child's input.
If the digest differs, the controller refuses to launch.
The sealed records in use continue to use their initial artifacts.

Codex refusals append advisory entries to `recovery-trace.jsonl` next to the graph.
The code `driver_launch_refused` identifies a setup or launch error.
The code `driver_prompt_digest_mismatch` identifies a snapshot that differs from its hash in the authorization.
The code `driver_authorization_refused` identifies an incorrect or consumed dispatch.

A refusal does not record the end of the work. Read `stderr.log` for the error from the child.
An advisory diagnostic log cannot grant authorization or repair the graph records.

Codex CLI 0.165.0 accepts the OAuth selector. See the [OpenAI authentication guide](https://learn.chatgpt.com/docs/auth#enforce-a-login-method-or-workspace).
Synthetic child probes show the source routing and credential filtering.
They cannot confirm a live OAuth login, native model execution, publication to an actual PR, or that a full loop qualifies.

The worker wrapper records `head_at_exit` in its `terminal.json` receipt after the child ends. It then publishes the receipt in one atomic operation.
The receipt token must equal the token in the launch record. Its exit code must equal the code in the worker result.
The exit HEAD before publication must equal the HEAD in the receipt.

The manifest records the published checkout HEAD in its own field. A root commit after the child exits cannot change the recorded exit HEAD.
Before the manifest exists, the checker accepts different JSON formatting if the bound values agree.
After the manifest exists, its raw seal hash also finds differences in formatting or other changes to the bytes.

Before an upgrade, finish pending publication with the runtime that made the run. Keep the artifacts and the qualification limits for that runtime.
A historical terminal receipt without a correct exit HEAD cannot prove that provenance. This version refuses qualification before publication for that receipt.
It does not fill the field from the current checkout or automatically select a previous runtime.

Other saved paths keep their checks if they do not use provenance before publication.
The same user can edit the receipt and seal. The checks can find changes to one record. They cannot detect coordinated changes to the two records.
