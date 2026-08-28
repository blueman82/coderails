# Coderails Factory

Factory is a separate local entry point: run `node factory/server.mjs`, then
open the loopback address it prints. It runs one selected provider for one
Factory run at a time. It accepts only server-configured, allowlisted project
and provider identifiers.

Factory starts the configured provider with the native Coderails
`agentic-loop` skill. The provider owns `progress.json`; Factory reads that
state and renders the real graph. Activity remains visible, with only clear
credential values masked and marked as such.

Factory does not change either dashboard, contact remote services, run a free
shell command, or track provider child processes. It is a local view and
launcher, not a remote execution monitor.
