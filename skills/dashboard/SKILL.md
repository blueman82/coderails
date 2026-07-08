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

Seven panels:

1. **SYSTEM VITALS** — usage windows, hooks fired, lint findings; hero
   numerals + sparklines. A source that can't be read locally shows
   "unavailable", never a guess.
2. **DIRECTIVES** — the active agentic loop's work units as a checklist
   (from `progress.json`), with an evals-frozen footer.
3. **DOCUMENTS / MEMORY.TRAIL** — newest-first feed across the wiki and
   memory directories.
4. **COMMAND DECK** — declared buttons (bounded, config-driven runs — never a
   free prompt box) plus run history, plus a Run Output viewer: click any
   run-history row to view its output — live-streaming while the run is
   still going, settled (fetched once) once it ends.
5. **PR GATES** — open PRs with gate state: merge-ready / blocked (missing
   artifact) / stale (SHA mismatch).
6. **Bottom-centre hero** — the active loop's primary directive with a big
   numeral (e.g. work units 2/7) and a micro ticker.
7. **Reserved slot** — placeholder for the assistant-agent sub-project until
   it lands.

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
launchd/install-dashboard-agent.sh     # bootstrap into gui/$UID
launchd/uninstall-dashboard-agent.sh   # bootout
```

This loads `launchd/com.coderails.dashboard.plist`, which runs
`skills/dashboard/runner/bin/dashboard-server.sh` with `RunAtLoad` and
`KeepAlive` set — launchd starts it at login and restarts it if it dies.
Logs go to `~/.claude/coderails-dashboard/dashboard.log`, same path
`start-dashboard.sh` uses.

**Once the agent is installed, `stop-dashboard.sh` does not stop it** — the
agent-owned server has no pidfile for `stop-dashboard.sh` to find. Stop it
with:

```
launchctl bootout gui/$UID/com.coderails.dashboard
```

Likewise, don't hand-run `start-dashboard.sh` while the agent is loaded:
both will fight over port 4173, and `KeepAlive` means launchd immediately
respawns its copy, so port 4173 crash-loops every `ThrottleInterval` (60s)
until one of the two is stopped.

## First run without a config

If `~/.claude/coderails-dashboard.json` doesn't exist yet, the server still
starts — it just runs with an empty config, so every panel renders its
explicit empty state (no repos polled, no buttons declared) instead of
erroring. Add the config once you're ready to point it at real repos, wiki
paths, and COMMAND DECK buttons; no restart-and-hope required beyond a normal
reload.

## Configuration

Config lives at `~/.claude/coderails-dashboard.json` (per-user; the watch
scope is machine-wide): which repos to poll, wiki/memory paths, and the
button declarations for the COMMAND DECK.

Buttons only ever run what this config declares. `POST /run` takes a button
name, looks it up in the config, and refuses anything undeclared — there is
no path from the dashboard to an arbitrary command.
