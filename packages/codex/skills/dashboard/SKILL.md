---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or invokes $coderails-codex:dashboard."
---

# Dashboard

Launch the local Coderails dashboard. It reads session, loop, wiki, memory,
PR, and run files on this machine. It shows current results in a web page.
It uses no new services and sends no telemetry away from this machine.

## What it shows

Seven panels:

1. **`SYSTEM VITALS`** shows use windows, hook counts, and lint results as large numbers and sparklines.
   Tiles show "loading…" until the first collection finishes. They then show the measured value.
   If the machine cannot read the source, the tile shows "unavailable".

2. **DIRECTIVES** shows one card for each live agentic loop with an update in the last 60 minutes.
   The card shows the title and the count of completed and total work units.
   It shows a checklist with each unit's status symbol (done / in-flight / pending).
   It also shows PR badges, recent decisions, and an evals-frozen footer.
   The `Live.N` counter in the section header shows the number of cards.

   Loops that are not complete and have no recent update move to a dim list below the cards.
   The list has one line for each loop with its title and time since its last update.

3. **CONTEXT TREND** shows one dot for each agentic-loop session.
   The x axis is the start date. The y axis is the orchestrator's cache-read token count for each assistant turn.
   It marks the 2026-07-17 token-reduction cutover. The series continues across the marker with no break or color change.
   It shows the median and sample count on each side. For counts below 20, the caption says the sample is too small to interpret.

   The panel makes no causal claim about token use and does not show a "saved X%" headline.
   It collects on its own SSE frame. The KPI tiles above do not wait for its transcript sweep.

4. **COMMAND DECK** shows declared buttons, run history, and a Run Output viewer.
   A button runs its bounded configured command. The deck has no free prompt box.
   Click a run-history row to view the output. The viewer streams it while the run continues.
   When the run ends, the viewer fetches its settled output one time.

5. **PR GATES** shows open PRs with gate status: `merge-ready`, `blocked`, or `stale`.
   A missing artifact blocks the gate. An incorrect SHA makes it stale.

6. **Bottom-center hero** shows the active loop's primary directive with a large number (e.g. work units 2/7) and a micro ticker.

7. **ASSISTANT.LINK** shows workflow-audit proposals for Approve or Deny.
   It also shows approved `workflow-audit:propose-skill` entries as the runner claims them and builds them locally.
   It shows when a person can examine and deliver the result.

## Starting

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`, then run
the bundled script from that directory:

```
"$SKILL_DIR/scripts/start_dashboard.py"
```

The first run installs dependencies (`npm ci`) and builds the app (`npm run build`).
Subsequent runs skip these steps if they find `node_modules` and a current `.next` build.
The script starts the production server (`npm run start`) on `127.0.0.1:4173`.
It writes the PID to `~/.codex/coderails-dashboard/dashboard.pid` and opens the dashboard in the browser.

Use `DASHBOARD_PORT` to change the default of 4173:

```
DASHBOARD_PORT=4200 "$SKILL_DIR/scripts/start_dashboard.py"
```

## LAN access (opt-in)

By default, the dashboard listens on `127.0.0.1`. Its check of the `Host` and `Origin` headers accepts only loopback.
To let devices on the same network connect, set `DASHBOARD_HOST` to this machine's LAN IP:

```
DASHBOARD_HOST=192.168.50.140 "$SKILL_DIR/scripts/start_dashboard.py"
```

The server listens on the configured address. Its default address is `127.0.0.1`.
The server accepts only loopback or the configured host in the `Host` and `Origin` headers.
On a different LAN device, open `http://<LAN-IP>:<port>` (e.g. `http://192.168.50.140:4173`).

If `DASHBOARD_HOST` is unset or empty, the listener and header check use only loopback.
The script exits with a non-zero status if startup receives a wildcard (`0.0.0.0`, `::`, `*`) or a `host:port` value.
The header check matches the literal configured host. A wildcard would cause HTTP 403 errors for LAN traffic.

**Access warning:** The dashboard runs declared commands without login.
This applies to the COMMAND DECK's `POST /run` and workflow-audit Approve/Deny.
The `Host` and `Origin` check protects the dashboard against hostile web pages or DNS rebinding through your browser.
It does not authenticate LAN devices. Devices on your LAN that can connect to the listener can start declared runs.

Use LAN access only on a trusted home network. Use a DHCP reservation or static lease for the host.
If the host's LAN IP changes, the dashboard reports a bind error on the next start.

## Stopping

```
"$SKILL_DIR/scripts/stop_dashboard.py"
```

The script stops the server with the PID in the file and removes that file.
The dashboard keeps its data only in its config and run-history files.

## First run without a config

If there is no `~/.codex/coderails-dashboard.json`, the server starts with an empty config.
Each panel shows its empty display without an error. The server polls no repositories and has no declared buttons.
Add the config when you have repository and wiki paths and COMMAND DECK buttons to declare.
Reload as usual. No restart is necessary.

## Configuration

Config lives at `~/.codex/coderails-dashboard.json` for each user. It names
the repos to poll, wiki paths, and COMMAND DECK buttons. The watch scope is
machine-wide.

Buttons run only commands declared in this config. `POST /run` looks up a
button name and rejects undeclared names. It cannot run an arbitrary command.
