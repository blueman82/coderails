---
name: dashboard
description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or invokes $coderails-codex:dashboard."
---

# Dashboard

Launch the local observability HUD for coderails: a live web view of what the
agentic system is doing right now, backed by files already on disk (sessions,
loop progress, wiki/memory, PR state, run history) — no new services, no
telemetry leaving the machine.

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
   `workflow-audit:propose-skill` entries as they claim, build locally, and
   become ready for human review and delivery.

## Starting

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`, then run
the bundled script from that directory:

```
"$SKILL_DIR/scripts/start-dashboard.sh"
```

First run installs dependencies (`npm ci`) and builds the app (`npm run
build`); later runs skip both when `node_modules` and a fresh `.next` build
already exist, so a re-launch is fast. Starts the production server
(`npm run start`) on `127.0.0.1:4173`, writes its pid to
`~/.codex/coderails-dashboard/dashboard.pid`, and opens the dashboard in the
browser.

Override the port with `DASHBOARD_PORT`:

```
DASHBOARD_PORT=4200 "$SKILL_DIR/scripts/start-dashboard.sh"
```

## LAN access (opt-in)

By default the dashboard binds to `127.0.0.1` and only accepts requests whose
Host/Origin resolve to loopback — nothing on the network can reach it. Set
`DASHBOARD_HOST` to your machine's LAN IP to allow other devices on the same
network to reach it too:

```
DASHBOARD_HOST=192.168.50.140 "$SKILL_DIR/scripts/start-dashboard.sh"
```

This does two things together, from the one variable: the server binds to
that exact address instead of `127.0.0.1`, and the request guard additionally
accepts that exact host (and only that host) alongside loopback on both the
Host and Origin headers. From any other device on the LAN, open
`http://<LAN-IP>:<port>` (e.g. `http://192.168.50.140:4173`).

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
"$SKILL_DIR/scripts/stop-dashboard.sh"
```

Kills the process recorded in the pidfile and removes it. The dashboard keeps
no state of its own outside the config and run-history files below.

## First run without a config

If `~/.codex/coderails-dashboard.json` doesn't exist yet, the server still
starts — it just runs with an empty config, so every panel renders its
explicit empty state (no repos polled, no buttons declared) instead of
erroring. Add the config once you're ready to point it at real repos, wiki
paths, and COMMAND DECK buttons; no restart-and-hope required beyond a normal
reload.

## Configuration

Config lives at `~/.codex/coderails-dashboard.json` (per-user; the watch
scope is machine-wide): which repos to poll, wiki paths, and the
button declarations for the COMMAND DECK.

Buttons only ever run what this config declares. `POST /run` takes a button
name, looks it up in the config, and refuses anything undeclared — there is
no path from the dashboard to an arbitrary command.
