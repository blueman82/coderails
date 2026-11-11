# Typed state and attestation

Use this guide when a Coderails hook or merge command refuses typed data or a status. The local hook reports a cause code. The GitHub workflow posts the trusted `integrity-review` status for a PR head.

## Integrity status

The shared parser in `scripts/lib/integrity_attestation.py` checks the newest status. Its Codex copy has the same bytes. The Claude merge hook and the two merge commands use this parser.

| Code | Meaning | Procedure |
|---|---|---|
| `attest_missing` | No status exists for this head. | Check the GitHub workflow run for the PR. |
| `attest_not_success` | The newest status did not succeed. | Read the cause and correct the PR records. |
| `attest_wrong_creator` | The login differs from the expected login. | Check `integrity_review.enabled` and the status poster. |
| `attest_not_bound` | The description does not have full `integrity=pass` and `sha=<head>` tokens. | Check the status format. Do not bypass the gate. |

With `integrity_review.enabled: true`, the expected login is `github-actions[bot]`. A legacy `machine_user` setting keeps its previous login until cutover. The GitHub workflow does not import the local parser. A test checks that the workflow's success description parses. Codex has no PreToolUse merge hook. Its merge command calls the shared parser.

Run `python3 scripts/lib/state_counters.py` to count `attest_*` denials. The Claude hook writes `pr_merge_gate/denied/<code>` when its payload has a session ID. The Codex merge command does not write that diagnostic log entry.

## Loop eval verdict

`loop_evals.read_loop_evals()` gives `EvalVerdict{status, tamper_code}`. Callers use its fields. If the eval blocks the end of the loop, the hook logs `loop_state_guard/blocked/eval_verdict_<status>`. The retro cost reader gives `CostReport{state, message}` and logs `cost_report=<state>`. Callers do not use the message text to select an outcome.

## Graph readiness

Run `graph_readiness.py <progress.json> <node>`. It prints JSON with `ready` and `reason_code`. Exit code 0 means the node can run. `predecessor_pending`, `node_unknown`, `node_not_pending`, `graph_blocked`, and `join_not_dispatchable` mean the node cannot run. `state_unreadable`, a missing script, or output that is not JSON means the check could not resolve readiness.

If the check can read the graph data but the node cannot run, it logs `graph_readiness/not_ready/<code>`. If it cannot read the data, it has no session ID for logging. Each `progress.json` write carries `updated_at`. A refused change leaves the bytes unchanged.

## Claude hook state

`<loop dir>/<session>/hook_state.json` owns absent-state grace and nudge dedupe. A session such as `ab` differs from `abc`. The hooks do not read `discipline.log` to make these decisions. A missing or torn status file does not release grace. A torn file suppresses a nudge and records `hook_state_unreadable`. Repair a torn file before you rely on the next nudge.

The status file is writable by the same user as the agent. It prevents accidental repetition. It does not stop a hostile same-user agent. Codex does not run the Claude `loop_state_guard`, `offload_push_guard`, or `unregistered_loop_guard` hooks. Codex uses the shared attestation parser and graph `updated_at` stamp.
