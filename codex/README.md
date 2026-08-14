# Coderails Codex runtime

This directory is the standalone Codex provider runtime. It accepts ordinary
JSON state and writes durable graph state; it does not read Claude hooks,
transcripts, environment variables, slash commands, or plugin paths.

The catalog files are intentionally provider-native: Codex resolves a skill by
ID, loads its instruction, and invokes the JSON graph runner or lifecycle
validator as required.
