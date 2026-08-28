# Coderails Factory

Factory is a separate local entry point: run `node factory/server.mjs`, then
open the loopback address it prints. It runs one selected provider for one
Factory run at a time. It accepts only server-configured, allowlisted project
and provider identifiers.

The activity view keeps only redacted evidence metadata. It does not expose
provider output, credentials, or a raw progress file. The demo graph is a
server-owned fixture; the browser cannot supply a file path or command.

Factory does not change either dashboard, contact remote services, run a free
shell command, or track provider child processes. It is a local view and
launcher, not a remote execution monitor.
