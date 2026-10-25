# Typed state and attestation

Use this guide when a Coderails hook or merge command refuses a typed state or status. The local hook reports a reason code. The GitHub Actions workflow posts the trusted `integrity-review` status for a PR head.

## Integrity status

The shared parser in `scripts/lib/integrity_attestation.py` checks the newest status. Its Codex copy has the same bytes. The Claude merge hook and both merge commands use this parser.

| Code | Meaning | Action |
|---|---|---|
| `attest_missing` | No status exists for this head. | Check the Actions run for the PR. |
| `attest_not_success` | The newest status did not pass. | Read its failure reason and fix the PR evidence. |
| `attest_wrong_creator` | The login differs from the expected login. | Check `integrity_review.enabled` and the status poster. |
| `attest_not_bound` | The description lacks whole `integrity=pass` and `sha=<head>` tokens. | Check the status format. Do not bypass the gate. |

With `integrity_review.enabled: true`, the expected login is `github-actions[bot]`. A legacy `machine_user` setting keeps its old login until cutover. The Actions workflow does not import the local parser. A test checks that the workflow's success description parses. Codex has no PreToolUse merge hook; its merge command calls the shared parser.

Run `python3 scripts/lib/state_counters.py` to count `attest_*` denials. The Claude hook writes `pr_merge_gate/denied/<code>` when its payload has a session ID. The Codex merge command does not write that trace row.

## Loop eval verdict

`loop_evals.read_loop_evals()` returns `EvalVerdict{status, tamper_code}`. Callers use its fields. They do not decide from the message text. A blocked completion writes `loop_state_guard/blocked/eval_verdict_<status>` to the trace. The retro cost reader returns `CostReport{state, message}` and logs `cost_report=<state>`.

## Graph readiness

Run `graph_readiness.py <progress.json> <node>`. It prints JSON with `ready` and `reason_code`. Exit code 0 means ready. `predecessor_pending`, `node_unknown`, `node_not_pending`, `graph_blocked`, and `join_not_dispatchable` mean not ready. `state_unreadable`, a missing script, or output that is not JSON means the check could not resolve readiness.

A readable not-ready state writes `graph_readiness/not_ready/<code>` to the trace. An unreadable state has no session to trace. Every `progress.json` write carries `updated_at`; a refused transition leaves the bytes unchanged.

## Claude hook state

`<loop dir>/<session>/hook_state.json` owns absent-state grace and nudge dedupe. A session such as `ab` does not match `abc`. The hooks do not read `discipline.log` to make these decisions. A missing or torn state file does not release grace. A torn file suppresses a nudge and records `hook_state_unreadable`. Repair a torn file before relying on another nudge.

The state file is writable by the same user as the agent. It protects against accidental repeat actions; it does not stop a hostile same-user agent. Codex does not run the Claude `loop_state_guard`, `offload_push_guard`, or `unregistered_loop_guard` hooks. Codex uses the shared attestation parser and graph `updated_at` stamp.
