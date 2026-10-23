# P3: human-only minting of action receipts

Status: built (unit U4, branch `feature/p3-signed-receipts`). Scope: how an action receipt for `gh pr merge` /
`git push` to main is minted so that an agent cannot mint its own, and what that does and does not guarantee.

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

The minting step is a separate OWNER-RUN command, signed with a passphrase-protected key:

1. `python3 scripts/authority_keys.py init` (owner, at a terminal) creates a passphrase-protected ed25519 key
   `~/.coderails/keys/receipt_ed25519` and a signers file. `ssh-keygen` prompts on `/dev/tty`; the tool refuses
   (`receipt_refused_no_tty`) when there is no terminal and never overwrites an existing key.
2. `python3 scripts/action_receipt_cli.py approve-action ...` computes the binding itself
   (`scripts/lib/action_binding.py`: repository, destination ref, SHA; the owner never types a SHA), signs the
   canonical receipt body with `ssh-keygen -Y sign` (namespace `coderails-receipt`), and refuses without a
   controlling terminal (`receipt_refused_no_tty`). An agent without the passphrase cannot mint.
3. The hook verifies the signature against a trust root, then the binding, then consumes the receipt atomically
   (`O_CREAT|O_EXCL`). Unsigned, wrongly signed, edited, stale, replayed, v1 and unbound receipts are all refused.
4. Trust root, in two tiers, with no environment-variable override (an env knob would be a bypass):
   - ROOT tier `/Library/Application Support/Coderails/receipt_signers`, honoured only when the file and its
     directory are owned by uid 0 and not group/other writable. The owner installs it with sudo
     (`authority_keys.py install-root` only prints the commands). This is the real boundary. It is NOT installed
     on this machine by this work.
   - USER tier `~/.coderails/keys/receipt_signers`. The agent runs as the same user and can write this file, so
     this tier is a cooperating-agent safeguard (traced `trust_root_user_tier`), not a boundary.
   - Neither present: `trust_root_missing`, deny.

## Residuals (what this does not stop)

- The user-tier trust root and the key directory are agent-writable. A hostile same-user agent can replace the
  signers file with its own key and sign its own receipts. Only the root tier prevents that. Until the owner runs
  the sudo install, treat the whole mechanism as a cooperating-agent safeguard.
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
- An agent that fills the receipts directory with junk `*.json` sorted ahead of the real one can push the real
  receipt past the 50-receipt cap (`MAX_RECEIPTS`). That denies, never allows (a denial-of-service, not a bypass).
- The hook fails open on its own exceptions (`action_authority_failed_open`, traced and written to stderr), so an
  input that makes `binding()` or `guarded_segments()` raise would allow. No such input is known; `binding()`
  returns None rather than raising for malformed commands. Fail-closed for enforce mode is not built.
- The root tier now checks the file and every ancestor directory (uid 0, not group/other writable), but it is not
  installed here, so the real boundary is not active until the owner runs the sudo install.

## Binding rules and default

The gate is default ON: absent or unreadable config, or any value other than `off` / `advisory`, is `enforce`
(`action_authority: off` is the explicit switch). To keep the repository+ref+SHA binding honest, a guarded command is
unbindable (`binding_unknown`, denied) when it:

- carries an env assignment prefix (`GIT_DIR=`, `GIT_CONFIG_*=`, `GH_REPO=`, any `NAME=value`), `git -c`, `--git-dir` or
  `--work-tree` (they retarget the action; the prefix is kept in the hashed segment so it is never silently stripped);
- is a bare or remote-only `git push` (push.default, `branch.*.remote` and `remote.*.push` decide the destination);
- is `gh pr merge` without `--match-head-commit <live head sha>` (or `gh api .../merge` without `sha=`). GitHub then
  refuses a merge whose head moved after the hook ran. `scripts/merge.py` pins the sha its own gates verified;
- names the PR ambiguously (a branch name, two PRs, a `-R` that disagrees with the PR URL, a combined short flag
  hiding a value option). The repository comes from `-R`, the PR URL or the api path, else `origin`.

`git push origin HEAD` binds the current branch (a detached HEAD is unbindable); the repository is the PUSH url
(`git remote get-url --push --all`), so `remote.<n>.pushurl` / `pushInsteadOf` are seen, and a remote with more than one
push url is unbindable (it would push to all of them while the receipt names one). A guarded segment that follows ANY
segment that is not a known read-only command in the same command (allowlist: `status`, `log`, `diff`, `show`,
`rev-parse`, `ls-remote`, `cd`, `echo`, `grep`, a `git push` to a remote other than `.`, a `gh pr merge`, ...; a
redirect, command substitution or unknown program is a mover) is denied `state_mutated_before_guard`: the bound sha
would be stale at execution (`git push . evil:feature`, `git worktree add -B`, `git filter-branch`, a write into
`.git`, ...). Scripts and aliases that mutate are seen only as unknown commands, and only within the same command: a
ref moved by an earlier, separate command is the state the hook binds.
A `cd` is parsed like a shell: a plain existing path moves the bound directory; a variable, `cd -`, a missing path, a
`( cd x && ... )` group, or a `cd` before `bash -c`/`eval` makes later guards unbindable (a pipeline `cd` is a subshell
and moves nothing).
Git global options before the subcommand (`-c`, `-C`, `--git-dir`, `--no-pager`) no longer hide a push from the
matcher, which also tightens `enforce_pr_workflow`. Codex has no `receipt_counters` mirror on purpose: the counters
read trace rows through the shared measurement script, which is provider independent.

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
