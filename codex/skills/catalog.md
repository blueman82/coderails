# Codex skill catalog

This is the native Codex implementation surface for every active node in
`skills/index.yaml`. Unknown IDs and missing required inputs fail closed.

Each indexed Codex route resolves here and records `provider: codex` plus
`implementation: codex/skills/catalog.md` in its durable result.
