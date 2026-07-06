**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Observability Dashboard Implementation Plan

**Goal:** Ship the coderails observability surface — a live local web HUD (Next.js/React Three Fiber) plus an Obsidian command-centre plugin — as a new skill in the coderails plugin, per `docs/coderails/specs/2026-07-06-observability-dashboard-design.md`.

**Architecture:** One local Next.js process serves both the R3F frontend and the API routes (SSE state stream + token-guarded `POST /api/run`). Collectors read state the kernel already produces (session dirs, `progress.json`, `gh` PR artifact markers, hook logs, wiki/memory mtimes). The Obsidian plugin is file-native: a code-block processor rendering vault state, sharing the same button config. Web dashboard ships first (Tasks 1–11), Obsidian wrapper last (Tasks 12–13).

## Global Constraints

- The literal string "v1" must not appear in any file this plan creates (owner mandate).
- Web UI is dark-only: no light theme, no `prefers-color-scheme` switching.
- Every HTML document starts with `<meta charset="utf-8">`.
- Server binds `127.0.0.1` only, never `0.0.0.0`.
- All dependency versions exact in `package.json` (no `^`/`~` ranges); `package-lock.json` committed; runtime install is `npm ci`.
- All child processes spawned via `execFile`/`spawn` with argv arrays — no shell string interpolation anywhere.
- WebGL is a progressive enhancement: all Three.js setup wrapped in try/catch with a deliberate 2D-canvas fallback.
- Single accent colour (dusty rose `#d9909a` idle) + global hue progression during runs; status via brightness/glyph, not extra hues.
- `prefers-reduced-motion` disables intro and heavy motion.
- Skill scaffold is created via the skill-creator tooling; frontend build is guided by the frontend-design skill with the spec's mockup assets as input.

## File map

```
skills/dashboard/
  SKILL.md                                  # trigger + usage (Task 1)
  scripts/start-dashboard.sh                # npm ci → build → start → open (Task 10)
  scripts/stop-dashboard.sh                 # (Task 10)
  app/                                      # Next.js app (Task 2)
    package.json / package-lock.json / next.config.mjs / tsconfig.json
    vitest.config.ts
    src/lib/config.ts                       # config load + fail-fast validation (Task 3)
    src/lib/runlog.ts                       # JSONL run records (Task 7)
    src/lib/collect/sessions.ts             # sessions + loops (Task 4)
    src/lib/collect/prGates.ts              # gh + marker grammar (Task 5)
    src/lib/collect/memoryTrail.ts          # mtime sweep (Task 6)
    src/lib/collect/health.ts               # usage/hooks/lint tiles (Task 6)
    src/app/api/events/route.ts             # SSE stream (Task 8)
    src/app/api/run/route.ts                # token-guarded trigger (Task 7)
    src/app/page.tsx + src/components/*     # HUD frontend (Task 9)
    src/components/sphere/*                 # R3F scene + 2D fallback (Task 9)
    test/*.test.ts                          # vitest suites (Tasks 3–8)
  obsidian/                                 # Obsidian plugin source (Tasks 12–13)
    manifest.json / package.json / esbuild.config.mjs / src/main.ts
    dist/main.js                            # committed build (wiki-init marp precedent)
docs/REFERENCE.md                           # catalogue entry (Task 11)
```

Repo-relative paths below assume the coderails repo root.

---

## Task 1 — Scaffold the dashboard skill

**Files:** `skills/dashboard/SKILL.md` (create), `skills/dashboard/scripts/` (create dir).

**Steps:**
- [ ] Invoke the skill-creator tooling (owner mandate) to scaffold a new skill named `dashboard` with description: "Launch the coderails observability dashboard — a live local web HUD showing sessions, agentic loops, PR gate states, runs, and memory activity, with declared one-click skill triggers. Use when the user says 'dashboard', 'observability', 'command center', 'watch the system', or '/coderails:dashboard'."
- [ ] In SKILL.md body, document: what the dashboard shows (the seven panels), how to start (`scripts/start-dashboard.sh`), how to stop, config location `~/.claude/coderails-dashboard.json`, and that buttons only run config-declared commands.
- [ ] Add frontmatter consistent with sibling skills (compare `skills/wiki-query/SKILL.md` for the house style).

**Interfaces produced:** skill name `coderails:dashboard`; scripts dir path used by Task 10.

**Verify:** `ls skills/dashboard/SKILL.md` exists; frontmatter parses (`head -8`); description contains trigger phrases; grep confirms no "v1" string.

---

## Task 2 — Scaffold the Next.js app with pinned dependencies

**Files:** `skills/dashboard/app/package.json`, `package-lock.json`, `next.config.mjs`, `tsconfig.json`, `vitest.config.ts`, `src/app/layout.tsx`, `src/app/page.tsx` (placeholder shell only — replaced in Task 9).

**Steps:**
- [ ] `npm create next-app` (App Router, TypeScript, no Tailwind — styling is bespoke CSS per spec) into `skills/dashboard/app`.
- [ ] Add runtime deps at exact versions (latest stable at implementation time, then frozen): `three`, `@react-three/fiber`, `@react-three/postprocessing`, `gsap`. Add dev deps: `vitest`, `@types/three`.
- [ ] Before committing GSAP: read its bundled LICENSE; if its terms disallow redistribution in this MIT repo, remove it and record in the plan-execution notes that the intro uses CSS/WAAPI instead (spec fallback).
- [ ] Rewrite all semver ranges in `package.json` to exact pins (no `^`); run `npm install` to regenerate the lockfile; commit lockfile.
- [ ] `next.config.mjs`: no special config beyond defaults; the start script (Task 10) passes `--hostname 127.0.0.1`.
- [ ] `src/app/layout.tsx`: `<meta charSet="utf-8">`, `<title>coderails — observability terminal</title>`, dark background body.

**Interfaces produced:** the app root `skills/dashboard/app` used by every later task; `npm run test` (vitest), `npm run build`, `npm run start` scripts.

**Verify:** `cd skills/dashboard/app && npm ci && npm run build` exits 0; `grep -E '"[~^]' package.json` returns nothing; `grep -ri '"v1"' src/` returns nothing.

---

## Task 3 — Config loader with fail-fast validation

**Files:** `skills/dashboard/app/src/lib/config.ts`, `skills/dashboard/app/test/config.test.ts`.

**Interfaces produced (consumed by Tasks 4–9, 12):**
```ts
export type PermissionProfile = 'read-only' | 'standard' | 'bypass';
export interface ButtonDef {
  name: string;            // unique key, e.g. "wiki-lint"
  label: string;           // deck label, e.g. "WIKI LINT"
  command: string;         // e.g. "/coderails:wiki-lint"
  cwd: string;             // absolute path the run executes in
  profile: PermissionProfile;
  inputAllowed?: boolean;  // one optional text arg
  bypassPermissions?: true; // required in addition when profile === 'bypass'
}
export interface DashboardConfig {
  repos: string[];         // "owner/name" polled via gh
  wikiPaths: string[];     // absolute dirs for memory-trail sweep
  memoryPaths: string[];
  buttons: ButtonDef[];
}
export function loadConfig(path?: string): DashboardConfig; // throws ConfigError with field-level message
```

**Steps (TDD per `coderails:test-driven-development`):**
- [ ] Write failing tests: valid config parses; missing file throws `ConfigError` naming the path; duplicate button names throw; `profile: 'bypass'` without `bypassPermissions: true` throws; relative `cwd` throws; unknown profile throws.
- [ ] Run tests, confirm they fail for the right reason (module missing / assertions unmet).
- [ ] Implement `loadConfig` (default path `~/.claude/coderails-dashboard.json`), minimal to pass.
- [ ] Re-run; commit.

**Verify:** `npm run test -- config` all green; intentionally break a fixture field and confirm the error message names the field.

---

## Task 4 — Sessions & loops collector

**Files:** `skills/dashboard/app/src/lib/collect/sessions.ts`, `test/sessions.test.ts`, `test/fixtures/projects/` (fixture tree mimicking `~/.claude/projects/<slug>/` with a `progress.json`).

**Interfaces produced (consumed by Task 8):**
```ts
export interface SessionInfo { project: string; lastActivity: number; state: 'active'|'idle'|'stalled'; }
export interface LoopInfo { slug: string; sessionId: string; workUnitsDone: number; workUnitsTotal: number; evalsFrozen: boolean; unitTitles: {title: string; done: boolean}[]; }
export function collectSessions(baseDir: string, now: number): SessionInfo[];   // active <5m, idle <60m, stalled ≥60m
export function collectLoops(baseDir: string): LoopInfo[];
```

**Steps (TDD):**
- [ ] Build fixtures: one fresh-mtime project dir, one idle, one stalled; one `progress.json` matching the real schema — copy a sanitised example from the shape defined by `hooks/scripts/lib/agentic_loop_path.sh` (path pattern `<base>/<slug>/<session_id>/progress.json`) and `hooks/scripts/tests/loop_state_guard_evals.test.sh` fixtures.
- [ ] Write failing tests: state thresholds at the boundaries (4m59s → active, 60m → stalled); loop parsing extracts unit counts and evals-frozen; malformed `progress.json` yields a loop entry with `evalsFrozen: false` and zero units rather than a throw (a broken loop file must still be *visible* — this surface reports, it does not gate).
- [ ] Implement minimally; re-run; commit.

**Verify:** `npm run test -- sessions` green; run `collectLoops` against the real `~/.claude` base on this machine and confirm it returns without throwing.

---

## Task 5 — PR-gates collector (gh + marker grammar)

**Files:** `skills/dashboard/app/src/lib/collect/prGates.ts`, `test/prGates.test.ts`, `test/fixtures/pr-comments/*.json`.

**Interfaces produced (consumed by Task 8):**
```ts
export type GateState = 'merge-ready' | 'blocked' | 'stale';
export interface PrGate { repo: string; number: number; title: string; headSha: string;
  review: 'present'|'missing'|'stale'; evals: 'pass'|'fail'|'missing'|'stale'; tier?: string; state: GateState; }
export function parseGates(prJson: unknown, comments: unknown[]): PrGate;      // pure, testable
export function collectPrGates(cfg: DashboardConfig): Promise<PrGate[]>;      // shells gh via execFile
```

**Steps (TDD):**
- [ ] Fixtures: real marker lines built with the grammar from `scripts/lib/eval-artifact.sh` (`<!-- coderails-eval-summary v1 pr=N head_sha=SHA result=R tier=T -->`) and `scripts/lib/review-artifact.sh`. NOTE: the marker grammar's own `v1` version token is upstream SSOT, not new text — the no-"v1" mandate applies to text this plan authors, and parsing must match the existing constant verbatim (read it from the shell lib at test-authoring time; do not retype from memory).
- [ ] Write failing tests: marker for matching SHA → present/pass; marker for older SHA → stale; no marker → missing; state derivation (review present + evals pass + SHAs match → merge-ready; anything missing → blocked; SHA mismatch → stale).
- [ ] Implement `parseGates` pure; implement `collectPrGates` calling `gh pr list/view --json` via `execFile` (never a shell string), catching non-zero exit into a `{repo, error}` marker the SSE layer renders as "unavailable".
- [ ] Re-run; commit.

**Verify:** `npm run test -- prGates` green; `collectPrGates` against this repo returns the real open-PR list (or empty) without throwing when `gh` is authenticated, and the "unavailable" path triggers with `GH_TOKEN=`-broken env.

---

## Task 6 — Memory-trail and health collectors

**Files:** `skills/dashboard/app/src/lib/collect/memoryTrail.ts`, `src/lib/collect/health.ts`, `test/memoryTrail.test.ts`, `test/health.test.ts`.

**Interfaces produced (consumed by Task 8):**
```ts
export interface TrailEntry { path: string; displayPath: string; mtime: number; }
export function collectMemoryTrail(dirs: string[], limit: number): TrailEntry[]; // newest-first across all dirs
export interface HealthTile { key: 'usage5h'|'usageWeek'|'hooksFired'|'lintFindings'; value: string|null; note?: string; }
export function collectHealth(): HealthTile[]; // value null + note 'unavailable: <reason>' when a source is unreadable
```

**Steps (TDD):**
- [ ] Failing tests: trail merges multiple dirs sorted by mtime with limit; nonexistent dir contributes nothing and no throw; health tiles return `value: null, note: 'unavailable: …'` when the underlying source is absent (fail-honest, never a guess — spec rule).
- [ ] Implement. Usage tiles: read only what is locally readable; if no reliable local source exists, ship the tile permanently as `unavailable` — do NOT scrape private files speculatively (YAGNI; resolved source can arrive later).
- [ ] Re-run; commit.

**Verify:** `npm run test -- memoryTrail health` green; live run lists real wiki files newest-first.

---

## Task 7 — Run endpoint: token, declared buttons, execFile, run log

**Files:** `skills/dashboard/app/src/app/api/run/route.ts`, `src/lib/runlog.ts`, `test/run.test.ts`.

**Interfaces produced (consumed by Tasks 8, 9, 12):**
```ts
// POST /api/run  body: { token: string; button: string; input?: string }
// 200 { runId: string } | 401 bad token | 404 undeclared button | 409 already running | 400 input not allowed
export interface RunRecord { runId: string; button: string; argv: string[]; cwd: string;
  profile: PermissionProfile; startedAt: number; endedAt?: number; exitCode?: number; outputPath: string; }
export function appendRun(rec: RunRecord): void;   // JSONL at ~/.claude/coderails-dashboard/runs/runs.jsonl
export function readRuns(limit: number): RunRecord[];
export function mintToken(): string;                // random per server start; embedded in page; required by /api/run
```

**Steps (TDD — these are the security invariants; tests first, no exceptions):**
- [ ] Failing tests: wrong/missing token → 401 and no spawn; undeclared button name → 404; `input` on a button without `inputAllowed` → 400; second request while running → 409; argv assembly for each profile — `read-only` → `claude -p <command> --allowedTools <read set>`, `standard` → `claude -p <command>`, `bypass` → `claude -p <command> --dangerously-skip-permissions` (exact flag names confirmed against `claude --help` at implementation time and frozen into the test expectations); `input` lands as one argv element, never concatenated; spawn is `execFile`-style (assert the mock received an array, not a string).
- [ ] Implement route with an in-memory per-button lock, `child_process.execFile('claude', argv, {cwd})`, stdout/stderr captured to `~/.claude/coderails-dashboard/runs/<runId>.log`, JSONL append on start and finish.
- [ ] Re-run; commit.

**Verify:** `npm run test -- run` green (≥7 tests); manual: declared test button firing `claude -p '/coderails:assumptions'` in this repo produces a JSONL record and a non-empty output file.

---

## Task 8 — SSE state stream

**Files:** `skills/dashboard/app/src/app/api/events/route.ts`, `src/lib/collect/index.ts` (aggregator), `test/events.test.ts`.

**Interfaces produced (consumed by Tasks 9, 12):**
```ts
// GET /api/events → text/event-stream. Named events, JSON data:
// 'snapshot' { sessions: SessionInfo[]; loops: LoopInfo[]; gates: PrGate[]; trail: TrailEntry[];
//              health: HealthTile[]; runs: RunRecord[]; token: string }
// 'runs'     RunRecord[]            (on any run start/finish)
// 'gates'    PrGate[]               (each gh poll, default every 120s)
// 'activity' { sessions, loops, trail }  (fs-watch driven, debounced 2s)
```

**Steps:**
- [ ] Write failing integration test: request the stream, assert first event is a complete `snapshot` within 3s and that a touched fixture file yields an `activity` event within the debounce window.
- [ ] Implement aggregator: fs.watch on the projects base + configured dirs (debounced), `setInterval` gh poll, run-log tap from Task 7. Collector errors degrade to their unavailable forms — the stream itself never dies on a collector throw (log once, keep serving; spec's error-handling rules).
- [ ] Re-run; commit.

**Verify:** `curl -N localhost:3000/api/events | head` shows the snapshot event; touching a watched file emits `activity`.

---

## Task 9 — HUD frontend: layout, sphere, run lifecycle

The largest task; it stays one task because the mockup is a single approved artifact a reviewer accepts or rejects whole. Reference assets: `docs/coderails/specs/assets/2026-07-06-observability/dashboard-mockup.html` (normative), the three `vault-reference-*.png` frames.

**Files:** `skills/dashboard/app/src/app/page.tsx`, `src/components/{Header,RailLeft,RailRight,BottomHero,HudCallout,RunProgress}.tsx`, `src/components/sphere/{Scene,NetworkSphere,GridFloor,Fallback2D}.tsx`, `src/styles/hud.css`.

**Steps:**
- [ ] Invoke the frontend-design skill (owner mandate) with the mockup + reference PNGs as input before writing components.
- [ ] Port the approved mockup's layout verbatim into components: three-column grid (330px/1fr/300px), header band, SYSTEM VITALS KPI stack with sparklines, DIRECTIVES checklist, MEMORY.TRAIL, COMMAND DECK + run history, PR GATES (◆/◇ glyphs), bottom hero, reserved ASSISTANT.LINK row. Data from the SSE hook, not fakes.
- [ ] Responsive: `@media (max-width: 1100px)` stacks header/left/right/hero into rows 1–4, body scrolls, callouts hidden (port the fixed media query from the mockup — the rails-overlap bug is already solved there; do not regress it).
- [ ] Sphere via R3F: 800–1500 nodes, plexus lines dominant, ~8% hub nodes larger/brighter, `FogExp2` tinted to the background colour (r128 lesson: white default fog brightens instead of dims under additive blending), static grid floor filling the lower third (visibility bar from the spec), clock-driven rotation/drift/breathing/twinkle, damped mouse parallax, bloom via postprocessing.
- [ ] 2D fallback: try/catch around canvas/context creation; on failure render the plexus in 2D canvas with identical palette and hue progression; `console.warn` once.
- [ ] Run lifecycle: fire button → optimistic deck state; SSE `runs` events drive RUNNING/ENGAGED states, header KERNEL·WORKING flip, tethered progress box (elapsed ticking, bar = elapsed/expected where expected = median of that button's last 5 durations from `readRuns`, fallback 30s), global hue sweep rose→violet→green by progress fraction (CSS custom property + same offset into the sphere material per frame), resolve flash, revert.
- [ ] Draggable callouts (pointer events, leader line follows), near-opaque backing.
- [ ] `prefers-reduced-motion`: skip GSAP intro, parallax, and animation loops; render one static frame.

**Verify:** with the dev server running and config pointing at this repo: side-by-side screenshot vs mockup at 1680px (layout parity by eye); resize to 1000px — no overlapping rails; DevTools "disable WebGL" (or override flag) → fallback renders and page stays interactive; fire a test button → observe working-state flips, progress box, hue sweep, history row; `grep -ri '"v1"' src/ styles/` empty.

---

## Task 10 — Launch scripts and skill wiring

**Files:** `skills/dashboard/scripts/start-dashboard.sh`, `scripts/stop-dashboard.sh`, edit `skills/dashboard/SKILL.md` (usage section).

**Steps:**
- [ ] `start-dashboard.sh`: resolve app dir relative to script; `npm ci` only if `node_modules` absent; `npm run build` only if `.next` absent or `src` newer; `npm run start -- --hostname 127.0.0.1 --port ${DASHBOARD_PORT:-4173}` backgrounded with pidfile under `~/.claude/coderails-dashboard/`; `open http://127.0.0.1:<port>`; follow the house style of `skills/brainstorming/scripts/start-server.sh` (existing precedent for skill-launched servers).
- [ ] `stop-dashboard.sh`: kill pidfile process, remove pidfile.
- [ ] SKILL.md usage: start, stop, port override, config bootstrap note (if config missing, the server starts with an empty config and every panel renders its explicit empty state — first-run is not an error).
- [ ] `chmod +x` both scripts (repo has an exec-bit invariant test — `hooks/scripts/tests/exec_bit_invariant.test.sh`).

**Verify:** from a shell: `skills/dashboard/scripts/start-dashboard.sh` on a machine state with no `node_modules` reaches a serving dashboard (first-run path); re-run is fast (skips ci/build); `stop-dashboard.sh` kills it; `hooks/scripts/tests/run_all.sh` still passes (exec-bit + no hook regressions).

---

## Task 11 — Docs catalogue entry

**Files:** `docs/REFERENCE.md` (edit — add `dashboard` to the skills catalogue in its existing table format).

**Steps:**
- [ ] Add the row/section for `coderails:dashboard` matching the surrounding entries' format (one-line purpose + invocation). Precedent: the task-evals entry added in commit `86176fc`.

**Verify:** `grep -n "dashboard" docs/REFERENCE.md` shows the entry; format visually matches neighbours.

---

## Task 12 — Obsidian plugin: scaffold + code-block processor + panels

**Files:** `skills/dashboard/obsidian/manifest.json`, `package.json` + `package-lock.json` (exact pins), `esbuild.config.mjs`, `src/main.ts`, `src/render.ts`, `dist/main.js` (committed build), `test/render.test.ts`.

**Interfaces consumed:** `DashboardConfig`/`ButtonDef` JSON shape (Task 3 — the plugin re-reads the same `~/.claude/coderails-dashboard.json`; it re-implements the reader in its own bundle but against the same documented JSON shape, with the shape asserted by a shared fixture file copied from the app's test fixtures).

**Interfaces produced:** fenced code block ` ```agentic-os``` ` in any note renders the command centre.

**Steps:**
- [ ] Scaffold from the official Obsidian sample-plugin TypeScript template; pin deps exactly; esbuild bundles to `dist/main.js` (committed — `skills/wiki-init/assets/obsidian-plugins/marp/main.js` is the precedent for shipping a built plugin).
- [ ] Register a markdown code-block processor for language `agentic-os` that renders (pure DOM, plugin-scoped CSS, amber-on-charcoal palette per the approved `obsidian-mockup.html`): token/stat cards from a metrics cache note (`dashboard-runs/_metrics.json` in the vault; absent → the shell-styled empty-state hint pattern), latest-merge banner, command grid from the shared config, activity feed from `dashboard-runs/*.md` (status chip = frontmatter `status:`, summary = first body line, row links to the note), footer heartbeat with blinking cursor (the page's only constant animation).
- [ ] `render.ts` kept pure (takes vault-state snapshot object, returns DOM) so vitest can cover it without Obsidian: failing tests first for empty-state, feed ordering, chip mapping pass/fail/needs-review.
- [ ] Re-run; commit.

**Verify:** `npm run test` green in `obsidian/`; `npm run build` reproduces `dist/main.js` byte-stable; manual: copy plugin dir into a scratch vault's `.obsidian/plugins/`, enable, insert the code block in a note → panels render; delete the metrics note → hint block appears.

---

## Task 13 — Obsidian buttons: intents + interim direct execution

**Files:** `skills/dashboard/obsidian/src/exec.ts`, `src/main.ts` (edit), `test/exec.test.ts`.

**Interfaces produced:** intent files `~/.claude/coderails-dashboard/queue/<runId>.json` matching `{button, input?, requestedAt, source: 'obsidian'}` — the seam sub-project 2's runner will consume ("intents write to system/queue — runner executes").

**Steps (TDD):**
- [ ] Failing tests: button press writes exactly one intent file with the declared shape; undeclared button never executes (config is the SSOT — same rule as the web deck); a press while that button's previous run is unresolved is rejected.
- [ ] Implement: press → write intent → (interim, desktop only, until sub-project 2) directly `execFile('claude', argv…)` with the same profile→flag mapping as Task 7, output captured to a new `dashboard-runs/<date>-<button>.md` note with `status:` frontmatter — which makes the activity feed update by construction.
- [ ] Feed row shows hourglass while unresolved, chip flips on completion (re-render on vault file change event).
- [ ] Re-run; commit.

**Verify:** in the scratch vault: press WIKI LINT → intent file exists, run note lands in `dashboard-runs/`, feed row flips to ✓; pressing an undeclared button (hand-edited block) renders an error row and spawns nothing.

---

## Task 14 — Eval gate (final)

**Files:** none created by hand — `/coderails:task-evals` owns its artifact.

**Steps:**
- [ ] Invoke `/coderails:task-evals` (scope: `pr`) against this plan's end state to generate and freeze the tiered success evals for the PR.
- [ ] After all implementation tasks pass their verify-criteria, grade the frozen evals and post the artifact via `/coderails:post-evals`.

**Verify:** the eval artifact exists on the PR, SHA-bound to the head commit, result `pass` — this artifact, not Task 13's verify-criteria, is the plan's definition of done (it gates `/merge`).

---

## Consciously accepted risks (pre-stress-test)

- Usage tiles may ship permanently "unavailable" if no reliable local source exists — accepted; honest absence beats scraping guesses.
- The Obsidian plugin duplicates a thin config reader rather than importing across bundles — accepted; the JSON shape is the contract, asserted by shared fixtures.
- Expected-duration pacing starts wrong for new buttons (30s fallback until 5 runs exist) — accepted; the bar is a pacing indicator by design.
