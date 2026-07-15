---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or '/coderails:dashboard'."
---

# Dashboard

Launch the local observability HUD for coderails: a live web view of what the
agentic system is doing right now, backed by files already on disk (sessions,
loop progress, wiki/memory, PR state, run history) — no new services, no
telemetry leaving the machine.

## What it shows

Six panels:

1. **SYSTEM VITALS** — usage windows, hooks fired, lint findings; hero
   numerals + sparklines. A source that can't be read locally shows
   "unavailable", never a guess.
2. **DIRECTIVES** — one card per live agentic loop (last updated within 60
   minutes): title, done/total work-unit count, a per-unit checklist with
   status glyphs (done / in-flight / pending), PR chips, recent decisions,
   and an evals-frozen footer. A `Live.N` counter in the section header
   tracks how many loop cards are showing. Non-complete loops that have
   gone stale drop into a dim sub-list below the cards, one line per loop
   with its title and time since last update.
3. **COMMAND DECK** — declared buttons (bounded, config-driven runs — never a
   free prompt box) plus run history, plus a Run Output viewer: click any
   run-history row to view its output — live-streaming while the run is
   still going, settled (fetched once) once it ends.
4. **PR GATES** — open PRs with gate state: merge-ready / blocked (missing
   artifact) / stale (SHA mismatch).
5. **Bottom-centre hero** — the active loop's primary directive with a big
   numeral (e.g. work units 2/7) and a micro ticker.
6. **ASSISTANT.LINK** — pending workflow-audit approvals awaiting a
   decision (Approve/Deny), plus build status for approved
   `workflow-audit:propose-skill` entries as they claim, build, and open a
   PR.

## Starting

```
scripts/start-dashboard.sh
```

First run installs dependencies (`npm ci`) and builds the app (`npm run
build`); later runs skip both when `node_modules` and a fresh `.next` build
already exist, so a re-launch is fast. Starts the production server
(`npm run start`) on `127.0.0.1:4173`, writes its pid to
`~/.claude/coderails-dashboard/dashboard.pid`, and opens the dashboard in the
browser.

Override the port with `DASHBOARD_PORT`:

```
DASHBOARD_PORT=4200 scripts/start-dashboard.sh
```

## LAN access (opt-in)

By default the dashboard binds to `127.0.0.1` and only accepts requests whose
Host/Origin resolve to loopback — nothing on the network can reach it. Set
`DASHBOARD_HOST` to your machine's LAN IP to allow other devices on the same
network to reach it too:

```
DASHBOARD_HOST=192.168.50.140 scripts/start-dashboard.sh
```

This does two things together, from the one variable: the server binds to
that exact address instead of `127.0.0.1`, and the request guard additionally
accepts that exact host (and only that host) alongside loopback on both the
Host and Origin headers. From any other device on the LAN, open
`http://<LAN-IP>:<port>` (e.g. `http://192.168.50.140:4173`).

For the persistent launchd agent, set `DASHBOARD_HOST` in the `plist`'s
`EnvironmentVariables` dict (it ships with an empty `DASHBOARD_HOST` entry —
fill in your LAN IP), then reinstall the agent
(`launchd/install-dashboard-agent.sh`) so launchd picks it up.

Leaving `DASHBOARD_HOST` unset (or empty) is unchanged from before this
option existed: bind and guard are loopback-only, identical to today.
Wildcard binds (`0.0.0.0`, `::`, `*`) and `host:port` forms are rejected at
startup with a non-zero exit — the guard exact-matches one host, so a
wildcard bind would silently 403 real LAN requests.

**SECURITY NOTE:** the dashboard has an unauthenticated command-execution
surface — the COMMAND DECK's `POST /run` and workflow-audit Approve/Deny both
execute declared commands with no login of any kind. The Host/Origin guard
defends against a hostile web page or DNS-rebinding attack reaching the
dashboard from your browser; it does **not** authenticate LAN devices. Any
device on your LAN that can reach the port can trigger declared runs. Only
enable LAN access on a trusted home network, and use a DHCP reservation or
static lease for the host — if the host's LAN IP changes, the dashboard will
fail to bind on next start rather than break silently.

## Stopping

```
scripts/stop-dashboard.sh
```

Kills the process recorded in the pidfile and removes it. The dashboard keeps
no state of its own outside the config and run-history files below.

## Surviving reboots (launchd)

To keep the dashboard running across reboots and crashes, install it as a
launchd LaunchAgent, mirroring the routine-sweeper agents in
`docs/routines.md`:

```
launchd/install-dashboard-agent.sh     # copy plist + bootstrap into gui/$(id -u)
launchd/uninstall-dashboard-agent.sh   # bootout + remove the copy
```

The installer copies `launchd/com.coderails.dashboard.plist` into
`~/Library/LaunchAgents/` and bootstraps from that copy, not from the repo
path — launchd only auto-loads plists that live in `~/Library/LaunchAgents/`,
so bootstrapping straight from the repo would silently stop surviving
reboots. The plist runs `skills/dashboard/runner/bin/dashboard-server.sh`
with `RunAtLoad` and `KeepAlive` set — launchd starts it at login and
restarts it if it dies. Logs go to `~/.claude/coderails-dashboard/dashboard.log`,
same path `start-dashboard.sh` uses.

**Once the agent is installed, `stop-dashboard.sh` does not stop it** — the
agent-owned server has no pidfile for `stop-dashboard.sh` to find. Stop it
with:

```
launchctl bootout gui/$(id -u)/com.coderails.dashboard
```

Likewise, stop any manual server (`bash skills/dashboard/scripts/stop-dashboard.sh`)
**before** running `install-dashboard-agent.sh` — the installer also refuses
to bootstrap if port 4173 is already held. Hand-running `start-dashboard.sh`
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
