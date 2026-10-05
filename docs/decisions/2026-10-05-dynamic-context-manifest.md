# Dynamic context manifest replaces the static bootstrap

Supersedes the "Bootstrap manifest: threshold not crossed, no change" section of
`docs/decisions/e4-bootstrap-and-codex-routing.md` (that record is left as written). The Codex routing proposal in E4
is untouched.

## Decision

The 8192 B threshold in `docs/graph-alignment-measurement.md` rule (b) was not crossed, and the owner asked for the
manifest anyway. SessionStart (startup, resume, clear, compact) now injects a code-generated manifest from
`hooks/scripts/lib/context_manifest.py` instead of the full `using-coderails` skill; UserPromptSubmit appends a
one-line `route:` from a small trigger table. The Codex copy of the module is byte-identical (cmp test in
`packages/tests/test_context_manifest.py`).

- Manifest lines: `coderails: active=yes`, authority (exact session id, unexpired), loop id/owner/state path/revision/
  ready nodes/hard stop (graph.py `inspect`), per-node evidence digest (read from progress.json: `inspect` lacks it),
  route, fixed constraints, fixed list-skills fail-safe.
- Foreign sessions see `loop: none`. State is found by exact session id; ids are never sanitised.
- Loop dir: Claude resolves `CLAUDE_AGENTIC_LOOP_DIR` then `CODERAILS_AGENTIC_LOOP_DIR`; Codex reads only
  `CODERAILS_` as before. The cwd's canonical slug dir is tried before the any-slug glob on both.
- The injected constraints keep the hard rules (must invoke an applicable skill, process skills first, subagents
  skip) without the 1% wording; the route is still advisory (a hook cannot enforce skill use).
- Routing is allow-list text matching: whole-word, case-insensitive, mid-prompt slash commands, negated keywords
  ("do not ingest") do not route. Unlisted phrasings get no route; the fail-safe line still points at the skill list.
- The "1% chance a skill applies" rule is removed from both `using-coderails` skills (`user-invocable: false` kept,
  so the model can still call the Skill tool explicitly).
- The route is advisory: a hook can only inject text, it cannot load a skill or enforce its use (inferred).
- Fail open: any error returns a static fallback manifest with the fail-safe line, exit 0, and a non-authoritative
  `trace.jsonl` row. Reason codes: `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`,
  `manifest_state_unreadable`, `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`.
  `route_none` writes no row. Events with no usable session id are filed under `_unattributed/trace.jsonl`.
- `inject_context.py` (Claude and Codex) uses the payload `cwd` with a `getcwd` fallback.

## Measured

Active loop manifest: Claude 499 B, Codex 486 B, versus 6288 B before (92% smaller than the Claude baseline only; no Codex before-figure was recorded, the old Codex text was a few hundred bytes plus a state path).
Empty payload floor: 258 B each. Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json`
(`bootstrap_bytes`, `context`).

## Not done

`coderails:execution-discipline` is left untouched: no pure-move test plan exists for a shared agent contract.
