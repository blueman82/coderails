# Observability Dashboard — Design

**Date:** 2026-07-06
**Status:** Approved by owner (design phase complete; mockups signed off)
**Sub-project:** 1 of 5 in the agentic-OS evolution sequence

## Context

Coderails today is the kernel of an agentic operating system: hooks, gates,
frozen evals, SHA-bound artifacts. What it lacks is a window — a surface where
the human watches what the system does, interactive or automated. This spec
defines that surface: a live local web dashboard plus an Obsidian command
centre, both reading state the kernel already produces and both able to fire
declared skill runs.

### The five-sub-project sequence (agreed 2026-07-06)

1. **Observability** (this spec) — web dashboard + Obsidian command centre.
2. **Routines** — scheduled, artifact-gated runs; defines the intent-queue +
   runner contract both dashboard surfaces consume.
3. **Workflow-audit skill** — mine session transcripts for repeated tasks;
   output is *created skills* (via existing authoring tooling), not a report.
4. **Assistant-agent kernel integration** — install coderails under the
   secretary; align its wiki to the coderails schema; promote its
   confirm-before-send prompt rules to hooks.
5. **Improvement loops / eval-runner** — feed past-run outcomes into future
   runs; un-defers the skill-eval-runner once routines produce a corpus.

Each sub-project gets its own spec → plan → implementation cycle. All five are
committed scope — nothing is deferred-by-stealth.

## Scope of this spec

Two deliverables, one data model:

- **Web dashboard** — a JARVIS-style HUD terminal ("VAULT direction") served
  by one local process.
- **Obsidian command centre** — a native Obsidian plugin rendering a
  mission-control note over vault state.

Shipped inside the coderails plugin as a new skill (working name
`coderails:dashboard`), created at implementation time via the skill-creator
tooling (owner mandate).

## Architecture — web dashboard

**Stack (owner decision, overriding the plain-Three.js recommendation):**
Next.js/React + React Three Fiber + postprocessing (bloom) + GSAP.
Consequences accepted: committed pinned lockfile, `npm ci` on first launch,
"fully offline after first install" replaces "no install step". One process,
one port: Next.js serves both the R3F frontend and the API routes.

- **Bind:** `127.0.0.1` only, never `0.0.0.0`.
- **Collect:** fs-watch `~/.claude/projects/*` (session activity; agentic-loop
  `progress.json` at the path defined by `hooks/scripts/lib/agentic_loop_path.sh`
  — the existing SSOT); poll `gh` per configured repo for open PRs and
  SHA-bound review/eval artifact markers (parse with the marker grammar from
  `scripts/lib/review-artifact.sh` / `eval-artifact.sh`); tail hook logs; stat
  mtimes across configured wiki/memory dirs.
- **Stream:** Server-Sent Events to the browser (EventSource reconnects
  natively).
- **Trigger:** one `POST /run` endpoint (see button model below).
- **Config:** `~/.claude/coderails-dashboard.json` (per-user — watch scope is
  machine-wide): repos to poll, wiki/memory paths, button declarations.

The dashboard is purely additive — no existing hook or script changes.

## Panels and data sources

1. **SYSTEM VITALS** (left rail) — usage windows (5h/week), hooks fired, lint
   findings; hero numerals + sparklines. If a usage source is not locally
   readable, the tile shows "unavailable", never a guess.
2. **DIRECTIVES** (left rail) — the active agentic loop's work units as a
   checklist (from `progress.json`), evals-frozen footer.
3. **DOCUMENTS / MEMORY.TRAIL** (left rail) — newest-first mtime feed across
   wiki + memory dirs.
4. **COMMAND DECK** (right rail) — declared buttons (bullet + micro label, no
   chrome) + run history rows; deck status line (IDLE/ENGAGED · n/N ACTIVE).
5. **PR GATES** (right rail) — open PRs with gate state: merge-ready /
   blocked (missing artifact) / stale (SHA mismatch), filled vs hollow glyphs.
6. **Bottom-centre hero** — primary directive (active loop) with big numeral
   (e.g. work units 2/7) and micro ticker.
7. **Reserved slot** — assistant-agent (sub-project 4); renders as an explicit
   dim placeholder until then.
8. **HUD callouts** — annotations tethered to the sphere for notable events
   (e.g. a PR reaching merge-ready): near-opaque backing, draggable, leader
   line follows, dismissible.

## Button / trigger model

A button is a declared, bounded run — never a free prompt box.

1. **Config-declared only.** `POST /run` takes a button name; the server looks
   it up in config and refuses anything undeclared. Optional single text
   argument only when the button declares `inputAllowed: true`; passed as a
   separate argv element (execFile-style spawn — no shell interpolation
   anywhere).
2. **Per-button permission profile** mapped to headless `claude -p` flags:
   - `read-only` — read-tool allowlist.
   - `standard` — inherit the target project's settings allowlists; headless
     unlisted actions fail rather than prompt (safe default).
   - `bypass` — permissions skipped; ugly config key on purpose
     (`"bypassPermissions": true`), warning badge in both UIs. Opt-in per
     button, never global.
3. **Anti-CSRF token.** Server mints a random token at startup, embeds it in
   the served page, requires it on every `/run` (localhost is reachable by any
   webpage the browser has open).
4. **Every run observable.** One run per button at a time (concurrent click
   rejected). Each run appends a JSONL record (button, argv, cwd, profile,
   start/end, exit code, output path) under `~/.claude/coderails-dashboard/runs/`;
   output captured to disk; failures render red with output attached. Silent
   failure is a spec violation.

**Shared contract (both surfaces):** the web deck and the Obsidian command
grid consume the SAME button config — one SSOT for name, command, cwd,
permission profile. A button added once appears in both. When sub-project 2
lands, both surfaces write intents to its queue ("intents write to
system/queue — runner executes"); until then the web server spawns directly.

## Run lifecycle and progress model

Click → queued → running → resolved (pass/fail) → recorded.

- Deck: label pulses "RUNNING…", status flips to ENGAGED · n/N ACTIVE, running
  command listed above the grid; header centre flips KERNEL · ONLINE →
  KERNEL · WORKING.
- A run-progress HUD box tethers to the sphere: command name, elapsed timer
  ("0:24 · working"), thin progress bar. **Progress is elapsed-vs-expected
  pacing** (expected = that button's historical durations), not true task
  progress — headless `claude -p` emits no progress stream. The bar is a
  pacing indicator; the completion flash is the truth.
- Global hue progression: while a run is active the ENTIRE theme's accent
  sweeps dusty rose → violet/magenta → green proportional to progress
  (CSS custom property + hue offset passed into the Three.js material each
  frame), easing back to rose on completion.
- Resolution: white flare + PASS ✓ (or ⚠ needs-review), history row appended,
  everything reverts to idle.

## Visual direction — web

Reference implementation: `assets/2026-07-06-observability/dashboard-mockup.html`
(approved 2026-07-06). Reference frames from the source material:
`vault-reference-working-state.png` (violet early-run),
`vault-reference-working-late-green.png` (green late-run, grid visibility),
`vault-reference-sphere-closeup.png` (sphere structure).

- Full-bleed 100vh HUD at desktop widths; hierarchy from type scale,
  letter-spacing, and 1px hairlines only — no cards, no fills.
- Monospace throughout; uppercase micro-labels (9–11px, 0.15–0.3em tracking);
  hero numerals 56–72px; one ~110px bottom-centre stat.
- Near-black warm background (#0d0708–#120a0c); single accent dusty rose
  #d9909a at idle; off-white numerals; warm mid-grey secondary. Status
  distinctions by brightness/glyph (filled ◆ vs hollow ◇), not extra hues.
- Wordmark: C.O.D.E.R.A.I.L.S + "AGENTIC OPERATING SYSTEM · OBSERVABILITY
  TERMINAL" expansion. Live clock. KERNEL/RUNNER status line.
- **The sphere** (centrepiece, doubles as system status): network-first —
  ~800–1500 nodes, plexus wiring is the dominant texture, node size hierarchy
  (~8% larger glowing hubs), depth dimming via dark-coloured fog
  (FogExp2 tinted to the background — three.js default white fog would
  brighten, not dim, under additive blending; verified against r128 source).
  Animation layers all clock-driven: slow Y rotation, per-particle noise
  drift, breathing scale, twinkle, throttled connection churn, damped mouse
  parallax, and run-state reaction (rotation/noise/brightness ramp + hue
  sweep).
- **Grid floor:** perspective wireframe clearly filling the lower third,
  running under/behind the sphere to a horizon; static; accent-tinted every
  frame (participates in the hue sweep). Visibility bar: "a user glancing at
  the page immediately says there is a grid."
- **Dark only.** No light theme, no `prefers-color-scheme` switching — this
  surface commits to one mood (regression lesson: an unrequested light theme
  inverted the whole design in a light-mode viewer).
- **WebGL is a progressive enhancement:** try/catch around all Three.js setup;
  on any context failure fall back to a deliberate 2D canvas plexus render
  (same palette, same hue progression). "GPU unavailable" is a real
  environment (hardware acceleration off) — the page must never be static or
  blank.
- **Responsive:** below ~1100px the HUD stacks (header / left rail / right
  rail / hero in separate grid rows, vertical scroll allowed, callouts
  hidden). The three-column no-scroll layout is the desktop experience only.
- GSAP intro ≤ ~2.5s (particles converge, plexus fades in last, staggered UI
  reveal). `prefers-reduced-motion` skips intro and heavy motion.
- `<meta charset="utf-8">` required (regression lesson: mojibake without it).

## Obsidian command centre

Reference implementation: `assets/2026-07-06-observability/obsidian-mockup.html`
(approved 2026-07-06). **Architecture supersedes the earlier thin-webview
idea.**

- **Native Obsidian plugin** (official TypeScript template), registering a
  code-block processor that renders the dashboard inside a real markdown note
  ("Command Center"). Everything on screen derives from files in the vault.
- **File-native data:** metrics cache as note/JSON in the vault (renders
  instantly from last-pulled state); completed runs land as notes in
  `dashboard-runs/`; the activity feed lists them with status chips and
  first-line summaries linking to the run note.
- **Buttons:** same shared config as the web deck. Press → intent written →
  runner executes (external runner owns execution so the dashboard works with
  Obsidian closed; until sub-project 2 provides the runner, the plugin may
  shell to headless `claude -p` directly on desktop as an interim).
- **Empty-state pattern:** shell-styled hint block pointing at the fix
  ("> no daily note at … / click [ PLAN TODAY ] or run /today").
- **Visual:** utilitarian, flat, no 3D. Warm charcoal (#161311, panels
  #1f1a17), burnt-amber accent (#e0915a), status-green dots/chips, monospace,
  corner-bracket framing on the token-burn hero, tab strip with
  [ BRACKETED ] active tab, footer runner heartbeat with blinking amber block
  cursor (the page's only constant animation).
- Panels: token burn gauge, four stat cards (open PRs / active sessions /
  hooks fired / lint findings), latest-merge banner, command grid, terminal
  hint, activity feed, runner footer.

## Error handling (deliberately minimal)

1. Source missing/unreadable → panel renders "unavailable: <reason>"; no retry
   machinery beyond the normal poll/watch cycle.
2. `gh` failure or rate-limit → keep last good data, show its timestamp.
3. Server errors → one log file, keep serving what works; browser reconnects
   via SSE; process death = rerun the command. No supervisor, no alerting.

## Testing

- Collector/parser tests (marker grammar reuse, progress.json reading, config
  validation) with fixtures, following `hooks/scripts/tests/` conventions.
- Run-endpoint security invariants: declared-button-only, token required,
  argv spawning (no shell), one-run-per-button, permission-profile flag
  mapping.
- Offline assertion: dashboard serves fully with no outbound network (after
  first install).
- Frontend verified by driving the real app (screenshots at desktop and
  stacked widths, WebGL-failure forced fallback, run lifecycle); no UI test
  framework.

## Non-goals

- **Voice interface** (the tutorials' AUDIO I/O / TTS panel) — excluded; its
  rail slot is repurposed (PR GATES on web, n/a in Obsidian).
- **Client/team distribution packaging** — the dashboard ships inside the
  public coderails plugin; deliberate client packaging is out of scope.

## Decisions log

| Decision | Choice | Note |
|---|---|---|
| Build order | Observability first | Watch window exists before everything else lands |
| Form | Live local web app + buttons in this spec | Read-only-first rejected by owner |
| Watch scope | All Claude activity machine-wide | |
| Home | Coderails repo, as a skill | Created via skill-creator (owner mandate) |
| Stack | Next.js/React + R3F, as briefed | Owner override of plain-Three.js recommendation |
| Dependencies | Committed lockfile + `npm ci` first launch | Vendoring node_modules rejected as unreasonable at React scale |
| Visual (web) | VAULT HUD brief + approved mockup | Supersedes earlier glassmorphism direction |
| Visual (Obsidian) | AGENTIC OS command-center brief + approved mockup | |
| Obsidian architecture | Native plugin over vault state | Supersedes thin-webview idea |
| Run progress | Elapsed-vs-expected pacing | `claude -p` has no progress stream |
| Naming | The literal string "v1" must not appear in any implementation text | Owner instruction |

## Implementation notes

- Create the skill via skill-creator; invoke the frontend-design skill for the
  frontend build with the two mockups + three reference PNGs as input.
- Pin exact library versions; record provenance. Verify GSAP's licence terms
  against redistribution in this MIT repo before committing any vendored file;
  fallback is CSS/WAAPI for the intro (one entrance sequence, not
  load-bearing).
- The sphere/fog subtlety is already researched (r128 source): keep fog colour
  equal to the background or use depth-based alpha.
