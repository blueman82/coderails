---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or invokes $coderails-codex:dashboard."
---

# Dashboard

Launch the local Coderails dashboard. It reads session, loop, wiki, memory,
PR, and run files on this machine. It shows live activity in a web page.
It needs no separate telemetry service. It does not send telemetry away
from this machine.

## What it shows

Seven panels:

1. **SYSTEM VITALS** — Shows usage windows, hook calls, and lint findings.
   Tiles show "loading…" until the first collection ends. A tile shows
   "unavailable" when its local source cannot be read. Otherwise, it shows
   the measured value.
2. **DIRECTIVES** — Shows one card for each loop updated in the last 60
   minutes. A card shows the title, completed and total work units, each
   unit's status, PRs, recent decisions, and frozen eval status. The
   `Live.N` counter shows the number of live cards. Older incomplete loops
   move to a dim list. Each line gives the loop title and age.
3. **CONTEXT TREND** — Shows one dot per loop session. The x-axis is the
   session start date. The y-axis is orchestrator cache-read tokens per
   assistant turn. An annotation marks the 2026-07-17 token-reduction
   change. The series has no gap or color change at that date. The panel
   makes no causal claim. It shows each side's median and sample count.
   A side with fewer than 20 sessions is marked too small to judge. The
   panel never claims a percentage saved. Its separate SSE frame keeps
   transcript collection from delaying the tiles above.
4. **COMMAND DECK** — Shows declared buttons and run history. It has no free
   prompt box. Select a run to view its output. Output streams during the
   run and is fetched once after the run ends.
5. **PR GATES** — open PRs with gate state: merge-ready / blocked (missing
   artifact) / stale (SHA mismatch).
6. **Bottom-centre hero** — the active loop's primary directive with a big
   numeral (e.g. work units 2/7) and a micro ticker.
7. **ASSISTANT.LINK** — Shows workflow-audit proposals that need Approve or
   Deny. It also shows local build status for approved
   `workflow-audit:propose-skill` entries. A finished build waits for human
   review and delivery.

## Starting

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`, then run
the bundled script from that directory:

```
"$SKILL_DIR/scripts/start_dashboard.py"
```

The first run installs dependencies with `npm ci`. It builds the app with
`npm run build`. Later runs skip these steps when `node_modules` and a fresh
`.next` build exist. The script starts the production server with
`npm run start` on `127.0.0.1:4173`. It writes the process ID to
`~/.codex/coderails-dashboard/dashboard.pid` and opens the browser.

Override the port with `DASHBOARD_PORT`:

```
DASHBOARD_PORT=4200 "$SKILL_DIR/scripts/start_dashboard.py"
```

## LAN access (opt-in)

By default, the dashboard binds to `127.0.0.1`. Its Host and Origin guard
accepts only loopback. Set `DASHBOARD_HOST` to this machine's LAN IP to
allow devices on the same network to connect:

```
DASHBOARD_HOST=192.168.50.140 "$SKILL_DIR/scripts/start_dashboard.py"
```

The server binds to that exact address. The request guard accepts that
host and loopback in Host and Origin headers. On another LAN device, open
`http://<LAN-IP>:<port>`. For example, use
`http://192.168.50.140:4173` for the command above.

With no `DASHBOARD_HOST`, bind and guard stay on loopback. The startup check
rejects wildcard addresses (`0.0.0.0`, `::`, `*`) and dotted IPv4
`address:port` values. Its current parser can accept other colon-bearing
strings, including `localhost:4173`; binding such a value may fail later.
Set `DASHBOARD_HOST` to a concrete host address without a port. The request
guard requires one exact host. A wildcard bind would make LAN requests fail
with 403.

**Security:** The dashboard has no login. COMMAND DECK `POST /run` and
workflow-audit Approve/Deny can run declared commands. The Host and Origin
guard limits hostile web pages and DNS rebinding through your browser.
It does not authenticate LAN devices. Any LAN device that can reach the
port can start a declared run. Enable LAN access only on a trusted network.
Use a DHCP reservation or a static address. If the host IP changes, the
dashboard fails to bind on the next start.

## Stopping

```
"$SKILL_DIR/scripts/stop_dashboard.py"
```

The script stops the process in the PID file and removes that file. The
dashboard keeps state only in its config and run-history files.

## First run without a config

The server starts without `~/.codex/coderails-dashboard.json`. It uses an
empty config. Panels show empty states; no repos are polled and no buttons
are declared. Add the config when you have repo and wiki paths and COMMAND
DECK buttons. Reload the page to see them.

## Configuration

Config lives at `~/.codex/coderails-dashboard.json` for each user. It names
the repos to poll, wiki paths, and COMMAND DECK buttons. The watch scope is
machine-wide.

Buttons run only commands declared in this config. `POST /run` looks up a
button name and rejects undeclared names. It cannot run an arbitrary command.
