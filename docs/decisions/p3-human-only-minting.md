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
- The hash covers only the command text the hook sees (not aliases, functions, `eval`/`xargs`, scripts that
  push). Binding is the repository, ref and SHA computed at hook time; a push by another route is not seen.
- A subagent whose `session_id` differs from the minter's is refused as `foreign_session` (documented limit).

## Counters and reason codes

Trace reason codes: `denied_signature_missing`, `denied_signature_invalid`, `denied_signer_unknown`,
`denied_trust_root_missing`, `denied_binding_unknown`, `denied_{hash,repository,ref,sha}_mismatch`,
`denied_consumed`, `trust_root_user_tier` (allow resting on the agent-writable tier), `receipt_consumed`,
`receipt_refused_no_tty`. `scripts/lib/receipt_counters.py: trust_summary()` counts them from trace counts; wiring
it into `measure_graph_alignment.py` is an integration step (that file is at its line limit).

## Measurement note

Per guarded command the hook runs `git` for the binding (push) or one `gh pr view` (merge, 4 s timeout) and two
`ssh-keygen` calls per candidate receipt per pass (peek, then consume). Measured once on this Mac (not a benchmark): a
gate test that creates two keys and runs two hook subprocesses takes about 0.5 s end to end, so one hook run is well under
a second with one candidate receipt; cost grows with the number of receipts in the session (cap 50, 2 `ssh-keygen`
calls each, per pass) and the hook timeout is 10 s.
