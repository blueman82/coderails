# Eval integrity runbook (Phase F)

[Provider parity measurements](graph-alignment-measurement.md).

The writer puts `eval_trace.jsonl` next to the corresponding `evals.json`. Loop scope uses the loop directory.
PR scope uses the directory of the eval file, so it does not have loop-safe storage. The entries are append-only, fail-open, and advisory.
The grader does not read them.

The fields are `schema_version, session_id, loop_id, timestamp, command, outcome, reason_code, event_id, inputs`.
The `inputs` values are SHA-256 hashes only. Each refusal also prints `reason=<code>` to stderr.
Run `python3 scripts/measure_graph_alignment.py --root . --json [--eval-trace <PR-scope file>]` to count `eval_trace` entries, deduplicated by `event_id`.

Query: `jq -r 'select(.outcome!="ok")|[.command,.outcome,.reason_code]|@tsv' <loop dir>/eval_trace.jsonl | sort | uniq -c`

| reason_code | Symptom | Remediation |
|---|---|---|
| `legacy_unhashed` | The suite has no `frozen_hash`. The grader gives outcome `legacy`. | No step is mandatory. To make a hash that detects edits, freeze again with `post_evals.py smoke-run` before grading. |
| `suite_hash_mismatch` | Oracle text differs from `frozen_hash` or the last signed change. | Revert the edit or apply it with `post_evals.py amend ...`. Then grade again. |
| `integrity_stripped` | The suite had `frozen_hash` at grading, but the hash is gone. The reader shows `TAMPERED:integrity_stripped`. | Put back the file. The reader cannot detect removal of the hash and tombstones together. |
| `legacy_unsigned` | The frozen suite has no `signature` and has no signature history. The outcome is `legacy` for `verify` or `loop-evals-read`. | No step is mandatory. To sign a new suite, freeze it with `post_evals.py smoke-run` with a key available. |
| `signature_invalid` | The signature check fails, the signature covers a different payload, or someone truncated and hashed the chain again. The payload has suite head, chain head and length, `loop_id`, and `session_id`. | Put back the file. Use `post_evals.py amend` for changes. It signs again. |
| `signer_unknown` | The signature passes the cryptographic check, but `allowed_signers` does not have its key. | Add the signer's public key line to `~/.coderails/keys/allowed_signers` only if you trust it. The signature uses a different key. |
| `signature_missing` | The signature is gone. The suite has `grading.signed: true`, is in the host's `signed_suites` ledger, or uses `evals.require_signatures: true`. The ledger in the keys directory catches removal and replacement before grading only on the signing host. The reader shows `TAMPERED:signature_missing`. | Put back the file. The `amend` command refuses to sign a stripped suite again. |
| `key_missing` | The verification host has no `ssh-keygen` or `allowed_signers`. Without mandatory signatures, the outcome is `degraded` and does not block. The command is `sign` if freeze leaves the suite unsigned. With `evals.require_signatures: true`, the check blocks. | Install OpenSSH or copy the public `allowed_signers` to `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`. |
| `key_perms` | Other users or group members can access the private key `evals_ed25519`. | `chmod 600 ~/.coderails/keys/evals_ed25519` |
| `sign_failed` | The `ssh-keygen` tool could not make a key or sign. | Run `ssh-keygen -Y sign` by hand to see the error. |
| `cmd_env` | Loop-scope `cmd` exited 126/127/>=128 during grading. | Correct the command's tooling or cwd. The `grade-loop` command runs it in the caller's cwd with a 10-second limit. |
| `chain_broken` | Someone edited or reordered an `amendment_chain` entry, or a chain has no `frozen_hash`. | Put back the file from the saved copy of the loop directory. Do not edit the chain by hand. |
| `chain_truncated` | The chain has fewer entries than `grading.chain_len`. | Put back the removed entries. The check cannot detect grading again after truncation. |
| `progress_missing` or `progress_unparseable` | The reader cannot find or parse `progress.json`, or the file has no `session_id` or `loop_id`. | Put `progress.json` back next to `evals.json`. There is no bypass flag. |
| `progress_foreign` | The suite has different IDs from `progress.json`. | The suite belongs to a different loop. Build it again for this loop. |
| `control_passes` | A loop-scope `negative_control` exited 0. | Change the control to report an error if the condition does not hold. |
| `control_env` | The control exited 126/127/>=128. The tool may be unavailable or the control may have timed out. | Correct the control's tooling or cwd. |
| `pass_exit_nonzero` | The eval records `pass`, but `cmd` exits nonzero in the gate. | The PASS is incorrect or the build regressed. Grade again. |
| `fixture_formula_not_in_cmd` | The `fixtures.formula` value is not the literal tail of `cmd`. | Make the fixtures run the actual checker text. |

The `grade-loop` and `amend` commands refuse with `key_missing` if they cannot check a signature before signing again.
They cannot replace a forged signature or one from an unknown source with a local signature.

## Signing trust boundary

Signing detects edits that someone makes without the key. It identifies the signer for the suite hash, chain head, `loop_id`, and `session_id`.
A different party can check the signature with only the public key, as an entry in `allowed_signers`.
A same-user agent can read the key with mode 0600 and sign again.
The signature cannot detect a rollback to a previously signed version. The `grading.chain_len` check gives a check for one type of rollback.

The key directory is `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`. The files are `evals_ed25519`, `.pub`, and `allowed_signers`.
All use mode 0600. The signer makes them on its first use.

If a workflow config exists, `evals.require_signatures` defaults to `true`. The check blocks unsigned suites and verification without the key.
Only an explicit `false` turns this off.

For signing, entries use `command=sign` with `ok|signed` or `degraded|key_missing`.
For verification, entries use `command=verify` with `ok|verified`, `legacy|legacy_unsigned`, or `degraded|key_missing`.
Refusals keep their command names. The `eval_trace_counts` counter uses `command|outcome|reason_code` and deduplicates by `event_id`.

The writer deduplicates by the `evals.json` SHA-256, command, outcome, and cause code. The log stops at 1 MiB.
Hook polling does not inflate counters. The value `smoke-run|ok|frozen` records each freeze.

## Refusal behavior

The `grade-loop` command without a sibling `progress.json` refuses with `progress_missing`, for example with archived or hand-built suites.
The two providers fail closed and have no bypass. The command also refuses a symlink to `progress.json` or a file with empty IDs.
The `smoke-verify` command refuses a PR-scope eval that records `pass` if its `cmd` exits nonzero. It gives `pass_exit_nonzero`.

After an unrecorded oracle edit, `smoke-run` refuses with `suite_hash_mismatch`. Use `post_evals.py amend`.
The Stop hook prints `reason=<code>` for a suite with tampering. A subsequent `grade-loop` run cannot clear it.
The log also uses `outcome=legacy` for `legacy_progress_schema`. A `progress.json` with `schema_version` other than 3 remains permitted.

## Reproduce

Run these commands on macOS without the `timeout` command, which macOS does not supply.

```
python3 -m unittest hooks.scripts.tests.eval_integrity_test hooks.scripts.tests.post_evals_grading_test scripts.tests.measure_graph_alignment_test
PYTHONPATH=. python3 -m unittest packages/tests/test_codex_grading_encoding.py
```
