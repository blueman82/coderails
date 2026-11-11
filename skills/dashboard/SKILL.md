---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or '/coderails:dashboard'."
model: sonnet
---

# Dashboard

Launch the local Coderails dashboard. It shows active sessions, loop status, wiki and memory changes, PR status, and run history. It reads files on this machine. It uses no new service and sends no telemetry.

## What it shows

Seven panels:

1. **`SYSTEM VITALS`.** Account use windows, hook counts, and lint results appear as large numbers and sparklines. Tiles show "loading…" until the first data collection ends. Then they show a value or "unavailable" if the source cannot be read locally.
2. **`DIRECTIVES`.** One card shows each live agentic loop with an update in the last 60 minutes. It shows the title, done and total work-unit counts, and a checklist with done, in-flight, and pending symbols. It also shows PR badges, recent decisions, and an evals-frozen footer. The `Live.N` counter gives the number of live cards. Older loops that are not complete appear in a dim list below. Each row shows the title and time since update.
3. **`CONTEXT TREND`.** One dot shows each agentic-loop session. The x axis is the start date. The y axis is orchestrator cache-read tokens for each assistant turn. The series continues through the 2026-07-17 token-reduction mark without a break or color change. The panel makes no causal claim about the cutover. It gives medians and n for each side. If n is below 20, it says the sample is too small to make a claim. It does not display a "saved X%" headline. The slow transcript sweep uses its own SSE frame so the KPI tiles can update first.
4. **`COMMAND DECK`.** Buttons run the commands declared in the config. There is no free prompt box. Select a run-history row to see its output in Run Output. An active run streams output. After it ends, the viewer fetches its output one time.
5. **`PR GATES`.** Open PRs show a status: `merge-ready`, `blocked` for a missing artifact, or `stale` for a SHA mismatch.
6. **Bottom-center panel.** The active loop’s primary directive has a large number, such as work units 2/7, and a small ticker.
7. **`ASSISTANT.LINK`.** Shows pending workflow-audit entries with `Approve` and `Deny` controls. It shows the claim, build, and PR-open status of approved `workflow-audit:propose-skill` entries.

## Starting

```
scripts/start_dashboard.py
```

On the first run, the script installs dependencies with `npm ci` and builds the app with `npm run build`.
On subsequent runs, it skips these steps when it finds `node_modules` and a current `.next` build.
It starts the production server with `npm run start` on `127.0.0.1:4173`.
It writes the PID to `~/.claude/coderails-dashboard/dashboard.pid` and opens the dashboard in the browser.

Set `DASHBOARD_PORT` to change the listener from `4173`.

```
DASHBOARD_PORT=4200 scripts/start_dashboard.py
```

## LAN access (opt-in)

By default, the dashboard binds to `127.0.0.1`.
The guard accepts loopback hosts in the `Host` and `Origin` headers.
To give other devices on the LAN access, set `DASHBOARD_HOST` to the machine's LAN IP:

```
DASHBOARD_HOST=192.168.50.140 scripts/start_dashboard.py
```

The server binds to that address. The guard then accepts that host and loopback.
It rejects other hosts in `Host` and `Origin`.
To open the dashboard from a device on that LAN, use `http://<LAN-IP>:<port>`, for example `http://192.168.50.140:4173`.

For the launchd agent, set `DASHBOARD_HOST` in the `plist`’s `EnvironmentVariables` dict.
It has an empty entry by default.
Set it to the LAN IP and install the agent again with `launchd/install_dashboard_agent.py`.

If `DASHBOARD_HOST` is unset or empty, the bind and guard stay on loopback only.
The server rejects wildcard binds (`0.0.0.0`, `::`, and `*`) and `host:port` values with a nonzero exit at startup.
The guard accepts one LAN host. With a wildcard bind, other LAN hosts would get HTTP 403.

**LAN access and authentication.**
The `COMMAND DECK` endpoint `POST /run` and the workflow-audit `Approve` and `Deny` controls run declared commands without a login.
The `Host` and `Origin` checks protect against hostile web pages and DNS rebinding through the browser.
They do not authenticate devices on the LAN.
A device with access to the dashboard address can start declared runs.

Use LAN access only on a trusted home network.
Use a DHCP reservation or static lease for the host.
If the host’s LAN IP changes, the server reports a bind error at the next startup.

## Stopping

```
scripts/stop_dashboard.py
```

This stops the server named in the PID file and removes the file.
The dashboard uses the config and run-history files below for stored data.

## Surviving reboots (launchd)

To keep the dashboard active across reboots and crashes, install the launchd LaunchAgent.
This follows the scheduler pattern in `docs/routines.md`.

```
launchd/install_dashboard_agent.py     # copy plist + bootstrap into gui/$(id -u)
launchd/uninstall_dashboard_agent.py   # bootout + remove the copy
```

The installer copies `launchd/com.coderails.dashboard.plist` to `~/Library/LaunchAgents/`.
It bootstraps the agent from the copy.
Launchd loads only the plists in `~/Library/LaunchAgents/` automatically for the user.
If you bootstrap from the repo, the agent does not start after a reboot.

The plist runs `skills/dashboard/runner/bin/dashboard_server.py` with `RunAtLoad` and `KeepAlive`.
Launchd starts it at login and starts it again if it stops.
Logs go to `~/.claude/coderails-dashboard/dashboard.log`, the path `start_dashboard.py` uses.

The plist sets `SoftResourceLimits.NumberOfFiles` to 4096.
A server that launchd starts inherits `launchctl limit maxfiles`, which is 256 on stock macOS.
An interactive shell can show a much higher value with `ulimit -n`. That value does not apply to the agent.
For each SSE connection, the dashboard opens a recursive `fs.watch` handle for each watched directory. Usual use can hit the limit at 256.

If the descriptor table is full, the server can accept TCP connections but cannot open files or watches.
The handlers give no data and send no SSE frames, so panels stay on "loading…".
To check this, compare `lsof -p <pid> | wc -l` with the limit.
A count that goes up across calls and does not go down indicates a leak.

**To stop the LaunchAgent, use the launchd command.**
The agent server has no PID file for `stop_dashboard.py` to read.

```
launchctl bootout gui/$(id -u)/com.coderails.dashboard
```

Before you run `install_dashboard_agent.py`, stop a manual server with `python3 skills/dashboard/scripts/stop_dashboard.py`.
The installer refuses to bootstrap if `4173` is in use.
If the agent server is active and you run `start_dashboard.py`, its lsof check refuses and exits 1.

If the agent starts while a manual server uses `4173`, it gets `EADDRINUSE`.
Launchd starts it again at each `ThrottleInterval` of 60s until one of the two servers stops.

## First run without a config

If there is no `~/.claude/coderails-dashboard.json`, the server starts with an empty config.
The panels show that there are no repos to poll or buttons to run.
When you have the repo paths, wiki paths, and `COMMAND DECK` buttons, add them to the config.
Reload the dashboard to use them.

## Configuration

The per-user config is `~/.claude/coderails-dashboard.json`.
It gives the repos to poll, wiki paths, and declared `COMMAND DECK` buttons.
The watch scope is machine-wide.

A button runs only a command in this config.
The `POST /run` endpoint reads a button name and looks it up in the config.
It refuses names with no declaration.
The dashboard cannot run arbitrary commands.
