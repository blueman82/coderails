# Coderails Codex runtime

This directory is the standalone Codex provider runtime. It accepts ordinary
JSON state and writes durable graph state; it does not read Claude hooks,
transcripts, environment variables, slash commands, or plugin paths.

The catalog files are intentionally provider-native: Codex resolves a skill by
ID, loads its instruction, and invokes the JSON graph runner or lifecycle
validator as required.

Live node records use the `codex-exec` adapter, which invokes the authenticated
host CLI as `codex exec --json --ephemeral --ignore-user-config -C <worktree> -`
with the node prompt on stdin. Fixture records continue to use explicit test
commands.

Run the host-authenticated acceptance path with
`python3 codex/tests/live_acceptance.py --state /tmp/codex-live.json`; rerun
with the same state to verify resume. `--scenario failure`, `missing`, and
`refusal` exercise fail-closed and completion-gate boundaries.
