# Shell classifier and receipt authority

[Runbook](RUNBOOK.md).

## Commit, push or ceiling gate behaves differently than the text suggests (argv classifier)

- Symptom: The result of `test_gate` for `git commit` or `destructive_bash_gate` for `--no-verify` or `-n` differs from the expected result.
  The `enforce_pr_workflow` or Codex authority hook can miss a `git -C d push origin main`.
  The ceiling may deny the third `run_all.py`, `test_codex_hooks.py`, or `post_evals.py post|validate-structure` after a branch rename.
  A second repo may have no denial. An edit on `main` can give `protected_paths_unreadable`.

### Shell context and classification

The `lib/shell_context.py` copies have the same bytes. They give source segments, unwrapped argv, and local directories for calls.
The `lib/argv_match.py` module classifies their Git and script operations.

The reader uses `; && || | & ( )`, backticks, and newlines as separators when the characters occur unquoted. It drops shell comments.
It unwraps assignments, leading redirections, shell keywords, and wrapper options for `env/sudo/command/exec/time/nohup/nice/timeout/stdbuf/setsid/xargs/uv run`.
It also unwraps absolute paths and `bash [-o x] -c '...'`.

Literal `cd`, `env --chdir`, and shell-c directories apply to their own shell scope. Successive relative Git `-C` options compose.
Test, workflow, and receipt reads for a repo use the initial Git prefix from the pre-Git directory.
This includes the two syntaxes for `--git-dir` and `--work-tree`, with the value attached or as a different argument.

For a protected push, Git directory options must select the physical worktree and Git directory in the payload.
A selector for the same worktree reaches the usual inspection check. An unknown or different selector causes a denial.
Help and dry-run flags skip the check only for their own operation.

The matcher uses the Git subcommand and decodes flags such as `-nm`. For scripts, it uses the basename and the first positional operation after recognized leading `--progress` options.
A path named `post` in `validate-embed` does not count as a workflow step. Plain quoted text such as `echo "git commit"` does not cause a check.
It checks command substitutions in double quotes.

If shlex cannot parse an unbalanced quote, whitespace splitting can select too many plain words. It sees only the first word in the resulting `-c` body.
The hooks refuse active Bash ANSI-C quotes and `-c` after shell options they do not recognize.

### Ceiling key and worktree counts

The key is `sha1(realpath(git common dir) + realpath(toplevel))` plus the target.
Files are in `<loop dir>/verification-ceiling/` or Codex `$PLUGIN_DATA/verification-ceiling/`.
A branch rename keeps its count. A linked worktree or second clone starts at zero.

To start the count again, remove the worktree count file and the current branch's legacy count file if there is one.
No message prints the digest. Calculate it or list the directory by mtime.

Each charge increases a legacy branch-keyed count if the file exists, with the two locks held.
This lets rollback keep the upgraded count. The hook does not make new legacy files, so new worktrees have their own counters.
The worktree key controls the current hook and keeps its count across renames. A crash between writes can make the legacy count too high.
A new worktree or renamed branch without a legacy file has no count continuity on rollback to a branch-keyed hook.

The mirror in `progress.json` writes `work_units[u].verification{run_all,post_evals}` only if the payload session and current `CLAUDE_LOOP_ID` own an in-progress schema-3 loop.
The physical worktree must have one corresponding unit. That unit must have an active `U3[<id>]` node in `active_wave.nodes`.
The mirror skips unknown or ambiguous inputs and inputs from a different session.

Codex uses the native file's durable regular flock in nonblocking mode and keeps file mode on atomic save.
Claude keeps its directory lock. A busy mirror or mirror error cannot skip the file counter.

One shell command can contain more than one counted run. The hook locks all affected counters in a fixed sequence and calculates their totals.
If a run goes above the ceiling, the hook blocks the command. It charges only the counters above the ceiling.

A disk error after an earlier write can keep some changes to counts. The hook blocks the command.
The two native `add-unit --worktree` CLIs record the unit's worktree. Fixture checks do not prove installed unit accounting.

### Protected path config

The `protected_paths_unreadable` code means the reader cannot find `policy/protected_paths.json` or the file is torn or has an incorrect shape.
This applies to the two plugin copies.
Until repair, `no_edit_on_main` and the in-Bash source-write check refuse all non-owner edits on `main` or `master`.
Owner permission files remain protected on all branches.

The keys are `source_extensions`, `plugin_source_globs`, `doc_extensions`, `doc_names`, and `settings_files`.
Add `.rs` to `source_extensions` to block `sed -i x.rs` on `main` without a code change.
The `no_edit_on_main` hook protects all suffixes that are not in `doc_extensions` or `doc_names`.

The hardcoded path `policy/protected_paths.json` also blocks Edit, apply_patch, and recognized in-Bash writes on `main` for the two copies.
This includes normalized `./` and `..` aliases. Owner settings paths normalize before the match on all branches.

Read `trace.by_reason` for `argv/denied/ceiling_exceeded` and `argv/denied/protected_paths_unreadable`.
Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.
See `docs/workflow-gates-measurement.md`.

### Classifier limits

The checker uses a parser for a subset of shell syntax. It checks literal `eval` bodies.
It cannot see aliases, shell functions, command names that expand at runtime, or calls to `git commit` or `run_all.py` from a script.

It models some wrapper options and does not expand shell values or use command-local `GIT_DIR` or `GIT_WORK_TREE` assignments.
Merge-script matching keeps its anchored source policy and its interpreter-option boundary. Git and GH operations use the shared context.
The checker recognizes abbreviated `--no-verify` flags.

A new worktree or clone starts a new counter. Subagent calls bypass the ceiling and the same user can edit its files.
This is a cooperating-agent safeguard.

## Action-authority hook denied a merge or push (or warned in advisory)

The hook denies `gh pr merge` or `git push` to `main` or `master` with "needs an action receipt (<code>)" in default enforce mode.
Explicit advisory can write an stderr warning with "action_authority (advisory)".
Only explicit `action_authority: off` disables the gate. An incorrect config gives `config_rejected`.

### Diagnostic queries and codes

Run `jq -r 'select(.command=="action_authority" or .command=="action_receipt") | [.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl`.
Or read `trace.receipts.by_reason_code` from `python3 scripts/measure_graph_alignment.py --root . --json`. The count deduplicates by `event_id`.

For `denied_<code>` and `advisory_<code>`, the suffix can be `no_receipt`, `hash_mismatch`, `repository_mismatch`, `ref_mismatch`, or `sha_mismatch`.
It can also be `signature_missing`, `signature_invalid`, `signer_unknown`, or `trust_root_missing`.
The `binding_unknown` code means the hook cannot calculate repository, ref, and SHA. The gate fails closed.
The `state_mutated_before_guard` code means an earlier step in the command moves a ref, HEAD, or remote before the gated operation.

Other suffixes are `expired`, `revoked`, `consumed`, `foreign_session`, `foreign_loop`, `kind_mismatch`, `no_session`, and `malformed`.
The `no_session` suffix means the payload had no `session_id`. The hook logs to `_no_session`.

The `receipt_consumed` code marks an accepted call. The `trust_root_user_tier` code means the check used an agent-writable trust root and accepted the call.
The `action_authority_failed_open` code means advisory without loaded live authority got an error and let the call continue.
The `denied_gate_error` code means enforce mode or loaded live authority got an unexpected error.
The `denied_budget_lock_unavailable` and `denied_budget_release_failed` codes mark merge budget lock or cleanup errors.
The hook keeps an ambiguous reservation spent.

The CLI writes `receipt_approved`, `receipt_revoked`, or `receipt_refused_no_tty`.
The `enforce_pr_workflow` hook also writes authority codes. It denies before consuming a receipt.

| Code | Meaning |
|---|---|
| `denied_authority_denied` | The session authority lists the category in `denied`. A receipt cannot override it. |
| `denied_max_prs_exceeded` | The session reached `max_prs`. The count uses `.executed` markers from all merge receipts and ignores their `authority_id`. A value of 0 means no merges. Use `authority.py` to narrow or grant again. |
| `approval_requirement_missing` | A permit verdict did not name mandatory approval. The hook refused before consuming a receipt. |
| `authority_denied_destructive_shell` | The destructive gate refused the force-with-lease family. |

The `scripts/merge.py` rows use `merge_py_<code>`, with refusals such as `no_receipt`, `no_session`, `binding_unknown`, `sha_mismatch`, and `consumed`.
An accepted operation logs `merge_py_receipt_executed`.
The `gate_summary(by_reason)` function in `scripts/lib/receipt_counters.py` supplies `gate` in the CLI output.
Integration into `measure_graph_alignment.py` belongs to that file's owner.

For an optional enforce-mode receipt for a merge, run:
`python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge --command 'python3 <absolute merge.py path> <N> --expected-head <40-hex PR head>' --cwd <repo dir>`.
The command `gh pr merge <N> --match-head-commit <40-hex PR head>` uses a receipt for its own full command text.
The `max_prs` count includes all executed merge receipts in the session. It includes receipts from before the authority grant.

### Pending reservations and markers

In advisory mode, live authority reserves a slot before plain `gh pr merge` runs. The hook cannot read the command result.
An unsuccessful command can keep a pending entry in `<loop dir>/<session>/merges/` and block a subsequent merge.
Check the PR and head on GitHub. If no merge occurred and the PR is open, an operator can release only that pending entry.

Use `scripts.lib.merge_budget.settle(path, False)` with `merge_budget.lock(session)` held. Keep completed entries because they record used budget.

A reservation cleanup or lock teardown error denies the command. The hook keeps a reservation if it cannot prove release.
Check the PR and head before you release the pending entry.

The `action_authority_failed_open` entry includes `inputs.error_class`, the SHA-256 of the error class name.
Compare it with `printf ZeroDivisionError | shasum -a 256`. The entry also has `loop_id` if known.
The hook log on stderr shows `action_authority failed open: <Class>: <message>`. An error with no session logs to `_no_session`.

The `marker_write_failed` and `executed_marker_unavailable` codes mean that a receipt note or execution marker could not be written.
The hook denies and rolls back only the new markers from that batch while it holds the claim lock.
The `marker_cleanup_failed` code means cleanup could not finish. Consumed markers stay if execution is uncertain.

Correct the file error and mint a new receipt. A stopped hook can record part of the spend. Check that the command did not run before manual recovery.

### Owner approval and command binding

For default enforce mode, the owner runs `python3 scripts/authority_keys.py init` one time at their terminal.
The `ssh-keygen` tool accepts an empty passphrase. The `show` command prints fingerprints.
Then the owner approves the full command with:

`python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge|git_push --command '<exact command>' --cwd <directory it runs in>`

The receipt must have a signature. A usable key without a passphrase can sign. Use `--key <public-key-path>` to select an available agent-backed key.
The approval CLI uses the owner's controlling terminal. An autonomy grant does not replace a receipt.
An agent must not make a PTY or invoke the signer to impersonate approval.

The receipt is single-use and defaults to 1h. The CLI calculates repository, ref, and SHA and signs.
It refuses without a tty with `receipt_refused_no_tty`. Add `--loop <loop id>` when the session authority has a loop.
The `inspect-receipt` and `revoke-receipt` commands take `--receipt-id`.

The `signer_unknown` or `trust_root_missing` code means the signers file does not list the key or cannot be found.
The `hash_mismatch` code means args, cwd, or branch differ from the approved command.
The `sha_mismatch` code means the push source HEAD or PR head moved after approval. Mint a new receipt.
The `git push origin feature:main` command binds the SHA of `feature`. The binding does not use HEAD.

The `foreign_session` code means the receipt uses a different `session_id`. Subagents share their parent's `session_id`.
Mint for the session that the hook reports. To disable the gate, set `action_authority: off` in `.coderails/workflow.config.yaml`.

Each gated segment of a chained command such as `a && b` must have its own receipt.
A leading `cd <dir>` changes the directory that the hash binds. Set `--cwd` to the directory where the command runs.
The binding comes from `scripts/lib/action_binding.py`. For push, it uses the refspec source SHA and destination ref.

For merge, it reads the live PR head with `gh pr view` and a 4-second timeout.
An unknown binding gives `binding_unknown` and fails closed.

Bindable pushes use `git [-C dir] push <remote> <ref>`, without an env prefix, `-c`, or `--git-dir`.
A push without an explicit refspec is gated and gives `binding_unknown`. The value `HEAD` alone means the current branch.
The repository is the push URL.

Bindable merges use `gh pr merge <n> --match-head-commit <live head sha>` or `gh api .../merge -f sha=<sha>`.
The `scripts/merge.py <n> --expected-head <live head sha>` command binds a helper receipt.
Bare `scripts/merge.py <n>` cannot bind in enforce mode because it gets the head after the hook.

The receipt must name the same helper path as the command. For Codex, use the absolute `packages/codex/scripts/merge.py` path.
Use `python3 <absolute helper path>` in enforce mode. Execution without `python3` has a different command hash and cannot bind to the receipt.

The gate checks `gh api --method PUT .../pulls/<n>/merge-async -f sha=<sha>` but cannot bind it.
GitHub can also merge open downstack PRs, so one receipt or slot cannot cover the effects.
The `enforce` mode and advisory with live authority deny it. Advisory without live authority warns and lets it continue.
Run ref-moving steps (`commit`, `branch -f`, `reset`, or `config`) in their own commands before the gated operation.

### Counters and limits

Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py`.
Read `receipts` and `trust` for signature, trust-root, binding, and `state_mutated_before_guard` counts.
One measured hook run with one receipt took less than 1 s. This is one measurement. A set of 50 receipts could get close to the 10-second hook timeout.

See `docs/decisions/p3-human-only-minting.md` for remaining limits.
The same user can edit the `.consumed` and `.revoked` marker files. Removal can let a receipt replay or clear revocation until expiry.
Files that fill the 50-receipt limit cause a denial. Unexpected errors deny in enforce mode or with loaded live authority.
Advisory without live authority lets the call continue on error.

An unreadable authority file looks missing in advisory mode.
A deeply nested file (`[` x 7000) in `authority.json` or `receipts/` gives a malformed result.
The `read_receipt` and `read_authority` functions catch `RecursionError`, so this causes a denial. This has the same trust boundary as the markers.

The hook checks `gh api` merge calls with the endpoint anywhere in argv. It also checks GraphQL `mergePullRequest` and `enablePullRequestAutoMerge`.
These GraphQL calls cannot bind and always cause a denial. Command hooks cannot see a web UI merge, `git merge` into `main` through a script, or a direct API tool call.

The Codex hook imports library copies with the same bytes and ships `scripts/action_receipt_cli.py` and `scripts/authority_keys.py`.
The same owner-run rules apply.

The user-tier trust root `~/.coderails/keys/receipt_signers` is agent-writable. This is a cooperating-agent safeguard.
Agents with Accessibility or control of the owner's terminal are out of scope. See `docs/decisions/p3-human-only-minting.md`.

The hash covers only command text the hook sees. It does not expand aliases, functions, eval/xargs, or scripts that push.
The hook unwraps sudo/time/subshell/`bash -c`/`gh api .../merge` wrappers. An env assignment prefix stays and makes the command unbindable.

Limits are 500 characters for scope, 8 KB for each receipt, and 50 receipts for each session.
The refusal codes are `receipt_refused_scope_too_long` and `receipt_refused_too_many`. The check protects only `main` and `master`.
