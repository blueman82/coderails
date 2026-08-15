# Coderails Codex package

This directory is the complete installable payload. Copy it elsewhere and run
`codex plugin install .`; it needs only Python 3 and the host's Codex OAuth.

The only repository-wide contract is the optional routing record at
`skills/index.yaml`. The runtime does not import, source, or discover any other
provider's files. Dispatch receives a JSON request and runs the requested
provider-native command; graph state is JSON and is atomically replaced.

`runtime/graph.py` is a generated standalone copy of the canonical
`codex/runtime/graph.py`. From the repository root, run
`python3 codex/scripts/sync_package_runtime.py` to refresh it and
`python3 codex/tests/runtime_parity.py` to fail on drift. The package copy is
kept so this directory remains independently runnable after installation.

## Enforcement ceiling

The lifecycle checker is mechanical when the Codex host invokes it, but this
package cannot force an invocation, inspect an omitted host action, or provide
server-side branch protection. Completion is accepted only after every node is
successful, teardown metadata exists, and the lifecycle checker returns zero.
Retries are bounded by each node's `retry.max` (0 through 5); exhausted work is
`hard-stop`, never silently successful.

Live node records use the package-local `codex-exec` adapter and the host's
authenticated `codex exec --json --ephemeral -C <worktree> -` CLI primitive;
fixture records remain explicit test commands.
