# Codex skill catalog

This is the native Codex implementation surface for every active node in
`skills/index.yaml`. The caller supplies `skill_id`, `inputs`, and `state` as
JSON. Unknown IDs and missing required inputs fail closed.

Supported IDs are the `coderails.*` entries in the root routing index. Each
skill returns its declared output contract and records `provider: codex` plus
`implementation: codex/skills/catalog.md` in the durable result.

Codex lifecycle enforcement is JSON-in/JSON-out through
`codex/hooks/lifecycle.py`; graph execution is through
`codex/scripts/run_graph.py`.
