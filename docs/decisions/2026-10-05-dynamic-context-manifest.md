# Dynamic context manifest replaces the static bootstrap

This decision supersedes the "Bootstrap manifest: threshold not crossed, no
change" section of `docs/decisions/e4-bootstrap-and-codex-routing.md`. That
record remains as written. The Codex routing proposal in E4 is untouched.

## Decision

The 8192 B threshold in `docs/graph-alignment-measurement.md` rule (b) was
not crossed. The owner asked for the manifest anyway. SessionStart now
injects a generated manifest from `hooks/scripts/lib/context_manifest.py`
on startup, resume, clear, and compact. It no longer injects the full
`using-coderails` skill. UserPromptSubmit adds one `route:` line from a
small trigger table. The Codex module is byte-identical; see the cmp test
in `packages/tests/test_context_manifest.py`.

- Manifest lines include `coderails: active=yes` and authority for an exact,
  unexpired session ID. They include loop ID, owner, state path, revision,
  ready nodes, and hard stop from `graph.py inspect`. A per-node evidence
  digest comes from `progress.json` because `inspect` lacks it. The
  manifest also carries the route, fixed constraints, and a fixed
  list-skills fallback.
- Foreign sessions see `loop: none`. State is found by exact session id; ids are never sanitised.
- Loop dir: Claude resolves `CLAUDE_AGENTIC_LOOP_DIR` then `CODERAILS_AGENTIC_LOOP_DIR`; Codex reads only
  `CODERAILS_` as before. The cwd's canonical slug dir is tried before the any-slug glob on both.
- The injected constraints retain the hard instructions to invoke an
  applicable skill and read process skills first. Subagents skip the
  bootstrap. The old 1% wording is removed. The route remains advisory;
  the hook cannot enforce skill use.
- Routing matches allowed text case-insensitively, by whole word. It also
  detects slash commands in the middle of a prompt. Negated phrases such
  as "do not ingest" do not route. Unlisted phrases get no route. The
  fallback line still points to the skill list.
- The "1% chance a skill applies" rule is removed from both `using-coderails` skills (`user-invocable: false` kept,
  so the model can still call the Skill tool explicitly).
- The route is advisory: a hook can only inject text, it cannot load a skill or enforce its use (inferred).
- Any error returns a static fallback manifest with the fail-safe line.
  The hook exits 0 and attempts a non-authoritative `trace.jsonl` row.
  Reason codes are `manifest_ok`, `manifest_graph_invalid`,
  `manifest_no_session`, `manifest_state_unreadable`,
  `manifest_payload_malformed`, `manifest_error`, `route_match`, and
  `route_payload_malformed`. `route_none` writes no row. Events without
  a usable session ID are filed under `_unattributed/trace.jsonl`.
- `inject_context.py` (Claude and Codex) uses the payload `cwd` with a `getcwd` fallback.

## Measured

For an active loop, the Claude manifest measured 499 B and the Codex
manifest measured 486 B. The earlier Claude text measured 6288 B, so its
manifest was 92% smaller. No earlier Codex measurement was recorded; the
old Codex text was a few hundred bytes plus a state path. The empty
payload floor was 258 B for each provider. Reproduce the measurements
with `python3 scripts/measure_graph_alignment.py --root . --json` and read
`bootstrap_bytes` and `context`.

## Not done

`coderails:execution-discipline` is left untouched: no pure-move test plan exists for a shared agent contract.
