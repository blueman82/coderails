# P3: signed action receipts

Status: introduced in draft PR #513.
Scope: signing and binding a receipt for `gh pr merge` or `git push` to `main`.
An agent with the same user ID can mint a receipt.

## Question

Can a macOS Keychain item and a native confirmation dialog limit minting to a human on this Mac?
The item would use user-presence or biometric access control. The dialog would have to refuse input from an agent.
The investigation used read-only probes.

## Investigation (read-only probes only; nothing created, no prompt, no TCC)

- Touch ID is enrolled for unlock. The `bioutil -r` command prints `Biometrics for unlock: 1`.
- The launchd session is Aqua, a GUI session. The `launchctl managername` command prints `Aqua`.
- The `swiftc` command is at `/usr/bin/swiftc` and uses Swift 6.4.
- The `security add-generic-password -h` command lists `-A` and `-T` for application ACLs.
  It gives no flag for biometry or for access that checks the user is there.
  A biometric Keychain item or `Secure Enclave` key must use `Security.framework` or `LocalAuthentication` through a compiled helper.
- The `ssh-keygen -Y sign` command fails with a passphrase-protected ed25519 key and no controlling terminal.
  A key that an agent makes without encryption can sign. The `ssh-keygen -Y verify` command refuses that signature against the owner's signers file.
  The `receipt_signing_test.py` and `action_receipt_test.py` tests check these conditions with `ssh-keygen`.

### NOT verified and NOT attempted

These checks would use a prompt, a new Keychain item, or a TCC grant:

- Can an unsigned CLI helper keep a `Secure Enclave` key or a user-presence Keychain item?
- Can `osascript` or `System Events` answer a native confirmation dialog?
  The result depends on an Accessibility TCC grant, which this work did not use.
- How do these prompts behave?

The probes did not show if the Keychain and dialog design can work. The implementation does not use it.

## Chosen design

Receipt minting uses a signing key. The owner can use a passphrase.

1. The owner runs `python3 scripts/authority_keys.py init` at a terminal.
   It makes the ed25519 key `~/.coderails/keys/receipt_ed25519` and a signers file.
   The `ssh-keygen` tool prompts on `/dev/tty`. The command refuses with `receipt_refused_no_tty` if there is no terminal.
   It does not overwrite a key. The owner can use an empty passphrase. Encryption is optional.

2. The `python3 scripts/action_receipt_cli.py approve-action ...` command calculates the repository, destination ref, and SHA.
   It uses `scripts/lib/action_binding.py`. The owner does not type a SHA.
   It signs the canonical receipt with `ssh-keygen -Y sign` in namespace `coderails-receipt`.
   It refuses without a controlling terminal (`receipt_refused_no_tty`).

   A key without a passphrase or `--key <public-key-path>` with an available signing agent can sign without a prompt.
   The owner must issue the approval command. An autonomy grant cannot replace it.
   Agents must not make a PTY or invoke the signer to impersonate owner approval.
   An agent with the same user ID can replace the user-tier signers file and use a different key.

3. The hook checks the signature against a trust root, then checks the binding.
   It then consumes the receipt atomically with `O_CREAT|O_EXCL`.
   It refuses unsigned, incorrectly signed, edited, stale, replayed, v1, and unbound receipts.

4. The trust root is `~/.coderails/keys/receipt_signers`.
   The agent runs as the same user and can write this file. This is a cooperating-agent safeguard.
   The `trust_root_user_tier` code marks its use. If the file is unavailable, the check gives `trust_root_missing`.

## Residuals (what this does not stop)

- The user-tier trust root and key directory are agent-writable.
  An agent with the same user ID can replace the signers file and sign its own receipts. This is a cooperating-agent safeguard.

- An agent with Accessibility permission or control of the owner's terminal can answer the passphrase prompt or type the command.
  Examples include input through a PTY or a shared tty.
  The tty rule excludes headless agents. An agent in the owner's session can have access.
  A key in `ssh-agent` can sign without a prompt.

- The hash covers only the command text the hook sees. It does not see aliases, functions, `xargs`, or scripts that push.
  The `guarded_segments` code normalizes quoting, absolute paths such as `/usr/bin/git`, `env` and `sudo` wrappers, `bash -c`, and `eval '...'`.
  It denies non-literal push destinations such as `HEAD:$B`, a glob, or `$(...)`, and the flags `--all` and `--mirror`.
  The hook cannot issue a binding for these commands. The binding uses repository, ref, and SHA at hook time. A push through a different path can be unseen.

- This historical scope excludes `gh api` writes that move a protected branch without a PR merge.
  Examples are `PATCH repos/o/r/git/refs/heads/main`, the contents API `PUT`, and GraphQL merge mutations.
  This scope does not include pushes to refs other than `main` or `master`, such as release branches. It does not include merges through the web UI or a different host.

- The agent can edit `.coderails/workflow.config.yaml` with Edit or Write.
  The setting `action_authority: off` disables the gate. The denial does not suggest this setting.
  The gate does not read mode from a root-tier or user-level file external to the repository.

- The hook refuses a subagent with a different `session_id` from the minter as `foreign_session`.

- Single-use and revocation use unsigned `<id>.consumed` and `<id>.revoked` marker files in the agent-writable receipts directory.
  The `O_EXCL` operation prevents races. A same-user agent can remove a marker.
  Removal of `<id>.consumed` can let a receipt replay until expiry. The owner sets the expiry, which defaults to 1 h.
  Removal of `<id>.revoked` can clear revocation.

  A consumed ledger that the agent cannot write could prevent this operation. Examples are a root-owned or append-only ledger. This implementation has no such ledger.

- A session lock covers selection, claim, note writes, and execution markers for all gated segments in one command.
  A synchronous error denies the command and removes markers from that call.
  If the hook cannot remove an execution marker, consumed markers stay to prevent reuse.
  A stop between writes can record part of the spend. Check that the command did not run before recovery.

- An agent that fills the receipts directory with `*.json` files can make a receipt unavailable. This occurs if those files sort before the receipt and put it after the 50-receipt cap (`MAX_RECEIPTS`).
  This causes a denial and cannot grant permission.

- An unexpected hook error denies a gated command in `enforce` or with loaded live authority (`denied_gate_error`).
  Advisory mode without live authority fails open and logs `action_authority_failed_open`.
  An error in the budget lock or reservation release denies the command and keeps an ambiguous reservation spent.

  The `read_authority()` function gives no authority on a read error. In advisory mode, an unreadable file can thus use the no-authority path.
  The user owns that file and can turn the mode off.

## Binding rules and mode

The gate defaults to `action_authority: enforce` with or without a configuration file.
The example and init settings also use `enforce`. An incorrect configuration denies operations that the gate checks.
Explicit `advisory` warns without a receipt. Explicit `off` disables this receipt gate.

A signed receipt must have an owner approval command. A passphrase is optional.

To check repository, ref, and SHA, the hook denies an unbindable command with `binding_unknown`.
These conditions prevent binding:

- The command has an env assignment prefix such as `GIT_DIR=`, `GIT_CONFIG_*=`, `GH_REPO=`, or `NAME=value`.
  It can also have `git -c`, `--git-dir`, or `--work-tree`. These can change the target. The hash keeps the prefix.

- The command is a bare or remote-only `git push`. The settings `push.default`, `branch.*.remote`, and `remote.*.push` determine its destination.

- The command is `gh pr merge` without `--match-head-commit <live head sha>`, or `gh api .../merge` without `sha=`.
  A bound command lets GitHub refuse a merge if the head changed after the hook ran.
  Bare `scripts/merge.py <n>` cannot bind in `enforce` mode.
  Use `scripts/merge.py <n> --expected-head <live head sha>` to attach a helper receipt.

- The `gh pr merge` target is ambiguous. Examples are a branch name, two PRs, or a `-R` value that differs from the URL. A combined short flag can also hide a value option.
  The helper resolves its `auto` or branch target before binding. The repo comes from `-R`, the PR URL, or the API path. If those sources give no repo, it uses `origin`.

The `git push origin HEAD` command binds the current branch. A detached HEAD cannot bind.
The repository is the push URL from `git remote get-url --push --all`. This includes `remote.<n>.pushurl` and `pushInsteadOf`.
More than one push URL prevents binding. The command would push to each URL, but a receipt names one.

The hook checks earlier segments in the same command.
If an unknown segment or a segment that can change data precedes a gated one, the hook gives `state_mutated_before_guard`.
The bound SHA could be stale.
Known read-only commands include `status`, `log`, `diff`, `show`, `rev-parse`, `ls-remote`, `cd`, `echo`, and `grep`.
A redirect, command substitution, or unknown executable can change data.

Negative probes include `git push . evil:feature`, `git worktree add -B`, `git filter-branch`, and a write into `.git`.
The hook binds the ref after changes from a different earlier command.

A literal `cd` to a directory changes the binding directory.
A path that uses shell expansion, `cd -`, a missing path, a `( cd x && ... )` group, or `cd` before `bash -c` or `eval` prevents binding.
A pipeline `cd` runs in a subshell. It does not change the directory for subsequent segments.

The matcher finds pushes with Git global options `-c`, `-C`, `--git-dir`, or `--no-pager`.
This also tightens `enforce_pr_workflow`.
Codex has no `receipt_counters` copy. The shared measurement script reads the logs from the two providers.

## Counters and reason codes

Codes include `denied_signature_missing`, `denied_signature_invalid`, `denied_signer_unknown`, `denied_trust_root_missing`, and `denied_binding_unknown`.
Other codes are `denied_{hash,repository,ref,sha}_mismatch`, `denied_consumed`, `trust_root_user_tier`, `receipt_consumed`, `receipt_refused_no_tty`, and `denied_state_mutated_before_guard`.
The `trust_root_user_tier` code marks an allow with the agent-writable trust root.

The `scripts/lib/receipt_counters.py: trust_summary()` function counts the codes.
Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py` for `receipts` and `trust`.
The measurement script is at its line limit. A change to add the counter there is a handoff.

## Measurement note

For each gated command, the hook runs `git` for a push binding or one `gh pr view` for a merge binding (4 s timeout).
For each candidate receipt it runs two `ssh-keygen` calls, to check and then consume it.

One test on this Mac made two keys and ran two hook subprocesses in about 0.5 s.
That measurement puts a hook run with one candidate receipt below a second.
Cost increases with the number of receipts in the session. The cap is 50 receipts, with two `ssh-keygen` calls each.
The hook timeout is 10 s.
