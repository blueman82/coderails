---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or '/coderails:dashboard'."
model: sonnet
---

# Dashboard

Launch the local Coderails dashboard. It shows current sessions, loop
progress, wiki and memory activity, PR state, and run history. It reads
files already on this machine. It sends no telemetry away.

## What it shows

Seven panels:

1. **SYSTEM VITALS** — usage windows, hooks fired, lint findings; hero
   numerals + sparklines. Tiles show "loading…" until the first activity
   collect resolves, then "unavailable" for a source that honestly can't be
   read locally (never a guess), or the value once collected.
2. **DIRECTIVES** — one card per live agentic loop (last updated within 60
   minutes): title, done/total work-unit count, a per-unit checklist with
   status glyphs (done / in-flight / pending), PR chips, recent decisions,
   and an evals-frozen footer. A `Live.N` counter in the section header
   tracks how many loop cards are showing. Non-complete loops that have
   gone stale drop into a dim sub-list below the cards, one line per loop
   with its title and time since last update.
3. **CONTEXT TREND** — one dot per agentic-loop session: x is the session's
   start date, y is orchestrator cache-read tokens per assistant turn. The
   2026-07-17 token-reduction cutover is drawn as an annotation the series
   runs straight through — no gap, no colour change, no causal claim.
   Per-side medians and n are shown side by side; a side below n=20 is
   captioned as too few to call. Whether the cutover reduced token burn is
   not established, and the panel is built to keep it that way: it never
   renders a "saved X%" headline. Collects on its own SSE frame, so its slow
   transcript sweep never delays the KPI tiles above.
4. **COMMAND DECK** — declared buttons (bounded, config-driven runs — never a
   free prompt box) plus run history, plus a Run Output viewer: click any
   run-history row to view its output — live-streaming while the run is
   still going, settled (fetched once) once it ends.
5. **PR GATES** — open PRs with gate state: merge-ready / blocked (missing
   artifact) / stale (SHA mismatch).
6. **Bottom-centre hero** — the active loop's primary directive with a big
   numeral (e.g. work units 2/7) and a micro ticker.
7. **ASSISTANT.LINK** — pending workflow-audit approvals awaiting a
   decision (Approve/Deny), plus build status for approved
   `workflow-audit:propose-skill` entries as they claim, build, and open a
   PR.

## Starting

```
python3 skills/dashboard/scripts/start_dashboard.py
```

The first run installs dependencies with `npm ci` and builds the app with
`npm run build`. Later runs skip these steps when `node_modules` and a fresh
`.next` build exist. The command starts the production server with
`npm run start` on `127.0.0.1:4173`. It writes the PID to
`~/.claude/coderails-dashboard/dashboard.pid` and opens the browser.

Override the port with `DASHBOARD_PORT`:

```
DASHBOARD_PORT=4200 python3 skills/dashboard/scripts/start_dashboard.py
```

## LAN access (opt-in)

By default, the dashboard binds to `127.0.0.1`. It accepts only Host and
Origin values that resolve to loopback. Set `DASHBOARD_HOST` to your machine's
LAN IP to allow access from other devices on that network:

```
DASHBOARD_HOST=192.168.50.140 python3 skills/dashboard/scripts/start_dashboard.py
```

The server then binds to that exact address. Its request guard accepts that
host and loopback in the Host and Origin headers. From another LAN device, open
`http://<LAN-IP>:<port>` (e.g. `http://192.168.50.140:4173`).

For the persistent launchd agent, set `DASHBOARD_HOST` in the `plist`'s
`EnvironmentVariables` dict (it ships with an empty `DASHBOARD_HOST` entry —
fill in your LAN IP), then reinstall the agent
(`launchd/install_dashboard_agent.py`) so launchd picks it up.

If `DASHBOARD_HOST` is unset or empty, the server binds to loopback.
The validator rejects wildcard binds (`0.0.0.0`, `::`, `*`) and dotted
IPv4 addresses with a port. Supply only the host address. The validator
also accepts some other colon-containing strings, which can fail when the
server tries to bind. The request guard matches the configured host.

**Security:** The dashboard does not require a login. COMMAND DECK's
`POST /run` and workflow-audit Approve/Deny execute declared commands.
The Host/Origin guard limits browser and DNS-rebinding requests. It does not
authenticate LAN devices. Any LAN device that can reach the port can start
declared runs. Enable LAN access only on a trusted network. Give the host a
DHCP reservation or static lease. If its LAN IP changes, the next start
fails to bind.

## Stopping

```
python3 skills/dashboard/scripts/stop_dashboard.py
```

Kills the process recorded in the pidfile and removes it. The dashboard keeps
no state of its own outside the config and run-history files below.

## Surviving reboots (launchd)

To keep the dashboard running across reboots and crashes, install it as a
launchd LaunchAgent, mirroring the routine-sweeper agents in
`docs/routines.md`:

```
launchd/install_dashboard_agent.py     # copy plist + bootstrap into gui/$(id -u)
launchd/uninstall_dashboard_agent.py   # bootout + remove the copy
```

The installer copies `launchd/com.coderails.dashboard.plist` into
`~/Library/LaunchAgents/` and bootstraps from that copy, not from the repo
path — launchd only auto-loads plists that live in `~/Library/LaunchAgents/`,
so bootstrapping straight from the repo would silently stop surviving
reboots. The plist runs `skills/dashboard/runner/bin/dashboard_server.py`
with `RunAtLoad` and `KeepAlive` set — launchd starts it at login and
restarts it if it dies. Logs go to `~/.claude/coderails-dashboard/dashboard.log`,
same path `start_dashboard.py` uses.

The plist also sets `SoftResourceLimits.NumberOfFiles` to 4096. A
launchd-spawned process inherits `launchctl limit maxfiles` — 256 on stock
macOS — **not** the much higher soft limit an interactive shell reports, so
checking `ulimit -n` in a terminal tells you nothing about the agent. The
dashboard opens a recursive `fs.watch` handle per watched dir per SSE
connection, and at 256 that ceiling is reachable in ordinary use. Once the
descriptor table is exhausted the process still accepts TCP but can no longer
open files or watches: every route returns nothing, no SSE frames arrive, and
panels sit on "loading…" forever. If you ever see that shape, check
`lsof -p <pid> | wc -l` against the limit — a count that climbs across
requests and never falls is a leak, not load.

**Once the agent is installed, `stop_dashboard.py` does not stop it** — the
agent-owned server has no pidfile for `stop_dashboard.py` to find. Stop it
with:

```
launchctl bootout gui/$(id -u)/com.coderails.dashboard
```

Likewise, stop any manual server (`python3 skills/dashboard/scripts/stop_dashboard.py`)
**before** running `install_dashboard_agent.py` — the installer also refuses
to bootstrap if port 4173 is already held. Hand-running `start_dashboard.py`
while the agent's server is healthy fails cleanly instead (its own lsof guard
refuses and exits 1, no fight). The real crash-loop risk is the reverse:
installing the agent while a manual server holds the port causes
EADDRINUSE, and launchd respawns the agent every `ThrottleInterval` (60s,
rate-limited — not immediately) until one of the two is stopped.

## First run without a config

If `~/.claude/coderails-dashboard.json` doesn't exist yet, the server still
starts — it just runs with an empty config, so every panel renders its
explicit empty state (no repos polled, no buttons declared) instead of
erroring. Add the config once you're ready to point it at real repos, wiki
paths, and COMMAND DECK buttons; no restart-and-hope required beyond a normal
reload.

## Configuration

Config lives at `~/.claude/coderails-dashboard.json` (per-user; the watch
scope is machine-wide): which repos to poll, wiki paths, and the
button declarations for the COMMAND DECK.

Buttons only ever run what this config declares. `POST /run` takes a button
name, looks it up in the config, and refuses anything undeclared — there is
no path from the dashboard to an arbitrary command.
