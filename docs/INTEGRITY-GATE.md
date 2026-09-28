# Integrity gate

The gate is a deterministic evidence check. It does not classify the change or
ask a model for a decision.

The required evidence is bound to the exact PR head SHA:

- review artifact and eval artifact are present and parseable;
- command results, policy paths, and provenance fields are valid;
- the changed-file set and diff stay within the configured bounds;
- the root-owned daemon posts `integrity-review` only after all checks pass.

Local `merge.py` and `enforce_pr_workflow` checks fail closed when the configured
machine-user status is missing, stale, malformed, or posted by another identity.
GitHub must separately require the `integrity-review` status on `main`; local
checks cannot replace that server-side boundary.

Authoritative files:

| Concern | File |
|---|---|
| Mechanical validation and status format | `scripts/integrity-gate/integrity_gate_runner.py` |
| Launchd configuration | `scripts/integrity-gate/com.coderails.integrity-gate.plist.template` |
| Local merge validation | `scripts/merge.py`, `hooks/scripts/enforce_pr_workflow.py` |
| Artifact format | `scripts/lib/eval_artifact.py` |
| Installation and promotion | `scripts/integrity-gate/install.py` |
| Owner-run ruleset and credential setup | `scripts/integrity-gate/setup.py` |

After changing the runner, run `scripts/integrity-gate/install.py` to promote it
to the root-owned install location. The owner-run setup helper creates or
verifies the protected GitHub `coderails-integrity-review` ruleset on `main`
before installing the daemon; it refuses to overwrite a same-name policy that
differs.

For a one-command product install, run the repository `install.py`. It offers
the gate but never executes `sudo` or handles credentials. The owner must run
the printed `python3 scripts/integrity-gate/setup.py` command manually; that
helper uses the owner's existing `gh` login for ruleset administration,
performs the machine-token check, and runs the privileged installation only
after explicit confirmation.
