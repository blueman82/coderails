# Dynamic context manifest replaces the static bootstrap

Supersedes the "Bootstrap manifest: threshold not crossed, no change" section of
`docs/decisions/e4-bootstrap-and-codex-routing.md`. This decision leaves the Codex routing proposal in E4 unchanged.

## Decision

The byte count was below the 8192 B threshold in rule (b) of `docs/graph-alignment-measurement.md`.
The owner asked for the manifest. SessionStart loads the manifest from `hooks/scripts/lib/context_manifest.py` in startup, resume, clear, and compact.
This replaces the full `using-coderails` skill at SessionStart. UserPromptSubmit appends a one-line `route:` from a small trigger table.

The Codex copy of the module has the same bytes. The cmp test is in `packages/tests/test_context_manifest.py`.

- The manifest lists `coderails: active=yes` and authority for the same session ID before expiration.
  It lists the loop ID, owner, data path, revision, nodes that can run, and hard stop from `graph.py inspect`.
  It lists the digest for each node from `progress.json`. The `inspect` output does not have this digest.
  It also lists routing, the fixed constraints, and the fallback line that points to the skill list.

- Sessions that do not own the loop see `loop: none`. The lookup uses the full session ID without changes.

- Claude checks `CLAUDE_AGENTIC_LOOP_DIR` and then `CODERAILS_AGENTIC_LOOP_DIR`.
  Codex continues to read only `CODERAILS_`. The two providers try the canonical slug directory for the cwd before they try a glob for all slugs.

- The manifest keeps the rules to use applicable skills, use procedure skills first, and skip the rule for subagents.
  It drops the 1% wording. The routing line is advisory.

- Routing checks an allowlist for full words with case-insensitive matching. It can find slash commands in the middle of a prompt.
  Negated keywords such as "do not ingest" and phrases not on the list produce no routing line. The fallback line points to the skill list.

- The two `using-coderails` skills no longer contain the "1% chance a skill applies" rule.
  They keep `user-invocable: false`, so the model can use the Skill tool directly.

- The hook can only add text. It cannot load a skill or make the model use it (inferred).

- On error, the hook gives a static manifest with the fallback line. It tries to log to `trace.jsonl` and exits with code 0.
  The codes are `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`, `manifest_payload_malformed`, `manifest_error`, `route_match`, and `route_payload_malformed`.
  The `route_none` outcome writes no entry. The hook uses `_unattributed/trace.jsonl` if it has no usable session ID.

- `inject_context.py` for Claude and Codex uses the payload `cwd` with a `getcwd` fallback.

## Measured

The active loop manifest uses 499 B for Claude and 486 B for Codex. The Claude baseline was 6288 B, so its reduction was 92%.
There is no Codex baseline measurement. The previous Codex text used hundreds of bytes plus the loop data path.
The empty payload minimum is 258 B for each provider.
Run `python3 scripts/measure_graph_alignment.py --root . --json` and read `bootstrap_bytes` and `context`.

## Not done

`coderails:execution-discipline` stays unchanged. There is no test plan for a move that preserves the shared agent contract.
