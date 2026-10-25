# P3: optional signed action receipts

Status: built in draft PR #513. Scope: how an optional action receipt for `gh pr merge` or `git push` to main is
signed and bound to the action. Same-user minting remains possible.

## Question

Can a macOS Keychain item with user-presence or biometric access control, plus a native confirmation dialog an
agent cannot answer, make minting human-only on this Mac, using only read-only probes?

## Investigation (read-only probes only; nothing created, no prompt, no TCC)

Verified, with the command that showed it:

- Touch ID is enrolled for unlock: `bioutil -r` prints `Biometrics for unlock: 1`.
- The launchd session is Aqua (a GUI session): `launchctl managername` prints `Aqua`.
- `swiftc` is present: `/usr/bin/swiftc`, Swift 6.4.
- The `security` CLI has no user-presence or biometry flag: `security add-generic-password -h` lists `-A`/`-T`
  (application ACLs) and nothing for biometry or user presence. A biometric Keychain item or a Secure Enclave key
  needs Security.framework / LocalAuthentication, i.e. a compiled helper.
- `ssh-keygen -Y sign` with a passphrase-protected ed25519 key and no controlling terminal fails; an agent-made
  unencrypted key signs, but `ssh-keygen -Y verify` against the owner's signers file rejects it. Both are
  re-checked on every test run with real `ssh-keygen` (`receipt_signing_test.py`, `action_receipt_test.py`).

NOT verified and NOT attempted (they would need a prompt, a created item, or a TCC grant):

- that an unsigned CLI helper can persist a Secure Enclave key or a user-presence Keychain item;
- that a native confirmation dialog cannot be driven by `osascript` / System Events (that depends on an
  Accessibility TCC grant this work did not touch);
- any prompt behaviour of the above.

So the Keychain-plus-dialog design is neither confirmed feasible nor ruled out. It is not built.

## Chosen design

Optional receipt minting can use a passphrase-protected key:

1. `python3 scripts/authority_keys.py init` (owner, at a terminal) creates an ed25519 key at
   `~/.coderails/keys/receipt_ed25519` and a signers file. `ssh-keygen` prompts on `/dev/tty`; the owner must enter
   a non-empty passphrase if they want the key protected by one. The init script does not check that the passphrase
   is non-empty. It refuses (`receipt_refused_no_tty`) without a terminal and never overwrites an existing key.
2. `python3 scripts/action_receipt_cli.py approve-action ...` computes the binding itself
   (`scripts/lib/action_binding.py`: repository, destination ref, SHA; the owner never types a SHA), signs the
   canonical receipt body with `ssh-keygen -Y sign` (namespace `coderails-receipt`), and refuses without a
   controlling terminal (`receipt_refused_no_tty`). When the owner chose a non-empty passphrase, an agent without
   it cannot sign with that key. An empty-passphrase key has no such barrier. A same-user agent can also replace
   the user-tier signers file and use another key.
3. The hook verifies the signature against a trust root, then the binding, then consumes the receipt atomically
   (`O_CREAT|O_EXCL`). Unsigned, wrongly signed, edited, stale, replayed, v1 and unbound receipts are all refused.
4. The trust root is `~/.coderails/keys/receipt_signers`. The agent runs as the same user and can write this file, so
   it is a cooperating-agent safeguard (traced `trust_root_user_tier`). If absent, verification reports
   `trust_root_missing`.

## Residuals (what this does not stop)

- The user-tier trust root and the key directory are agent-writable. A hostile same-user agent can replace the
  signers file with its own key and sign its own receipts. Treat this as a cooperating-agent safeguard.
- An agent with Accessibility permission or control of the owner's terminal (pty injection, a tty it shares) can
  answer the passphrase prompt or type the command. The tty rule excludes headless agents, not a hostile process
  in the owner's session. A key loaded in `ssh-agent` could also sign without a prompt.
- The hash covers only the command text the hook sees (not aliases, functions, `xargs`, scripts that push).
  Quoting, absolute program paths (`/usr/bin/git`), `env`/`sudo` wrappers, `bash -c` and `eval '...'` strings are
  normalised by `guarded_segments`; a non-literal push destination (`HEAD:$B`, a glob, `$(...)`), `--all` and
  `--mirror` are guarded and unbindable (denied). Binding is the repository, ref and SHA computed at hook time; a push
  by another route is not seen.
- Out of scope, so not guarded: `gh api` writes that move a protected branch without a PR merge (`PATCH
  repos/o/r/git/refs/heads/main`, the contents API `PUT`, graphql merge mutations); pushes to protected branches other
  than `main`/`master` (release branches); merges through the web UI or another host.
- The mode switch lives in `.coderails/workflow.config.yaml` inside the repository, which the agent can edit with
  Edit/Write (no hook guards that key). `action_authority: off` therefore disables the gate for a hostile same-user
  agent; it is an honest same-user boundary like the user-tier trust root. The deny text no longer suggests it. A
  mode read from a root-tier or user-level file outside the repo is not built.
- A subagent whose `session_id` differs from the minter's is refused as `foreign_session` (documented limit).
- Single-use and revocation live in unsigned `<id>.consumed` / `<id>.revoked` marker files in the agent-writable
  receipts directory. `O_EXCL` stops races, not `unlink`: a same-user agent can delete `<id>.consumed` to replay a
  receipt until it expires (owner-chosen, default 1 h) or delete `<id>.revoked` to un-revoke it. Only a consumed
  ledger outside the agent's write reach (root-owned or append-only) would close this; it is not built.
- A session lock covers selection, claim, note writes and execution markers for every guarded segment in one
  command. A synchronous failure denies and removes markers this call created. If an execution marker cannot be
  removed, consumed markers stay in place so the receipt cannot be reused. A process killed between marker writes
  can leave a partial spend. The batch is not crash-atomic; confirm the command did not run before recovery.
- An agent that fills the receipts directory with junk `*.json` sorted ahead of the real one can push the real
  receipt past the 50-receipt cap (`MAX_RECEIPTS`). That denies, never allows (a denial-of-service, not a bypass).
- An unexpected hook error denies a guarded command under `enforce` or after live authority loads
  (`denied_gate_error`). Advisory mode without live authority still fails open and traces
  `action_authority_failed_open`. A failed budget lock or reservation release denies and keeps an ambiguous
  reservation spent. `read_authority()` maps a file read error to no authority; in advisory mode, an unreadable
  authority can therefore take the no-authority path. The user owns that file and can also turn the mode off.

## Binding rules and mode

The gate is off unless config sets `action_authority: enforce` or `action_authority: advisory`. Thus a normal PR
workflow does not require a key or passphrase. To keep the repository+ref+SHA binding honest, a guarded command is
unbindable (`binding_unknown`, denied) when it:

- carries an env assignment prefix (`GIT_DIR=`, `GIT_CONFIG_*=`, `GH_REPO=`, any `NAME=value`), `git -c`, `--git-dir` or
  `--work-tree` (they retarget the action; the prefix is kept in the hashed segment so it is never silently stripped);
- is a bare or remote-only `git push` (push.default, `branch.*.remote` and `remote.*.push` decide the destination);
- is `gh pr merge` without `--match-head-commit <live head sha>` (or `gh api .../merge` without `sha=`). GitHub then
  refuses a merge whose head moved after the hook ran. Bare `scripts/merge.py <n>` is unbindable in enforce mode.
  Use `scripts/merge.py <n> --expected-head <live head sha>` to bind a helper receipt;
- names the PR ambiguously in `gh pr merge` (a branch name, two PRs, a `-R` that disagrees with the PR URL, a
  combined short flag hiding a value option). The helper resolves its `auto` or branch target before it binds.
  The repository comes from `-R`, the PR URL or the api path, else `origin`.

`git push origin HEAD` binds the current branch. A detached HEAD is unbindable. The repository is the push URL from
`git remote get-url --push --all`, including `remote.<n>.pushurl` and `pushInsteadOf`. More than one push URL is
unbindable because the command would push to each URL while a receipt names one.

The hook checks earlier segments in the same command. A guarded segment after an unknown or state-changing segment
is denied as `state_mutated_before_guard`: its bound SHA could be stale. Known read-only commands include `status`,
`log`, `diff`, `show`, `rev-parse`, `ls-remote`, `cd`, `echo` and `grep`. A redirect, command substitution or unknown
program may change state. Negative probes include `git push . evil:feature`, `git worktree add -B`, `git
filter-branch` and a write into `.git`. A ref changed by a separate earlier command is the state the hook binds.

A plain `cd` to an existing path changes the binding directory. A variable path, `cd -`, a missing path, a
`( cd x && ... )` group, or `cd` before `bash -c` or `eval` makes later guards unbindable. A pipeline `cd` runs in a
subshell and changes no directory for later segments. Git global options (`-c`, `-C`, `--git-dir`, `--no-pager`) no
longer hide a push from the matcher; this also tightens `enforce_pr_workflow`. Codex has no `receipt_counters` mirror:
the shared measurement script reads trace rows from both providers.

## Counters and reason codes

Trace reason codes: `denied_signature_missing`, `denied_signature_invalid`, `denied_signer_unknown`,
`denied_trust_root_missing`, `denied_binding_unknown`, `denied_{hash,repository,ref,sha}_mismatch`,
`denied_consumed`, `trust_root_user_tier` (allow resting on the agent-writable tier), `receipt_consumed`,
`receipt_refused_no_tty`, `denied_state_mutated_before_guard`. `scripts/lib/receipt_counters.py: trust_summary()` counts
them from trace counts. It has its own CLI, so the counters are reachable without editing the measurement script:
`python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py` (prints `receipts` and
`trust`). Folding the same call into `measure_graph_alignment.py` itself is a handoff (that file is at its line limit).

## Measurement note

Per guarded command the hook runs `git` for the binding (push) or one `gh pr view` (merge, 4 s timeout) and two
`ssh-keygen` calls per candidate receipt per pass (peek, then consume). Measured once on this Mac (not a benchmark): a
gate test that creates two keys and runs two hook subprocesses takes about 0.5 s end to end, so one hook run is well under
a second with one candidate receipt; cost grows with the number of receipts in the session (cap 50, 2 `ssh-keygen`
calls each, per pass) and the hook timeout is 10 s.
