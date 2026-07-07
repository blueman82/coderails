# @coderails/dashboard-lib

The single source of truth for the intent-queue/runner contract's
consumer-side pieces: the `Intent` schema and the `RoutineDef`/routines
section of `DashboardConfig`. The base `ButtonDef`/`PermissionProfile`/
`loadConfig` and the `buildArgv` profile→flag mapping are NOT owned here —
they live in `skills/dashboard/app/src/lib/config.ts` and `argv.ts`
(merged via PR #25) and this package imports them rather than
re-implementing them.

## The queue seam is LIVE

As of PR #25, `skills/dashboard/obsidian/src/exec.ts` already writes
intent files to `~/.claude/coderails-dashboard/queue/<runId>.json` on
every button press, matching this package's `Intent` type exactly:

```typescript
interface Intent {
  button: string;       // matches a ButtonDef.name or is the routine's own trigger name
  input?: string;       // optional freeform text, never parsed as a flag (see buildArgv)
  requestedAt: number;  // epoch-ms (Date.now()), NOT an ISO string
  source: "web" | "obsidian" | "cli" | string;
}
```

`parseIntent(raw: unknown): Intent` validates and returns a typed `Intent`,
throwing `IntentValidationError` on any malformed input. A compile-time
test (`test/schema-compat.test.ts`) type-checks this `Intent` type against
the obsidian plugin's own `IntentFile` type on every build, so producer
and consumer cannot silently drift apart.

`IntentFile.source` is presently the single literal `"obsidian"` on the
wire (the only merged producer); `Intent.source`'s wider union exists to
admit future producers (`"web"`, `"cli"`), not because they exist today.

**Interim producer behaviour, not part of this contract:** the obsidian
plugin currently ALSO direct-execs `claude` itself after writing the
intent file (see `obsidian/src/exec.ts`'s `pressButton`) — it does not
yet wait for the runner to claim and execute the queued intent. This is
the producer's own transitional behaviour on the way to the runner
becoming the sole executor; it is not something this package's contract
endorses going forward, and it is out of scope for this loop to change
(see Global Constraints: `app/`/`obsidian/` code is not modified here).

## The runner is the sole executor (target state)

No surface other than the runner (`skills/dashboard/runner`) may
invoke the `claude` CLI for a queued or scheduled run. This is a
permanent design rule for every surface wired to this queue, going
forward from this loop — even though the obsidian plugin's current
interim behaviour (above) does not yet honor it.

### Lifecycle

A queued intent file moves through exactly these directories, atomically
claimed by rename (never copied, never edited in place):

1. `queue/<runId>.json` — written by a producer (web click, Obsidian
   command, routine scheduler). Not yet claimed. Directory is created
   with mode `0o700` by producers (see `obsidian/src/main.ts`).
2. `processing/<runId>.json` — claimed by the runner via `fs.renameSync`.
   The atomicity of a same-filesystem rename is what prevents two runner
   instances from double-claiming the same intent.
3. On success: `archive/<runId>.json` — never deleted, subject to a
   configurable retention prune.
4. On malformed input (fails `parseIntent`): `quarantine/<runId>.json` —
   the sweep continues past it rather than crash-looping.

## Config: buttons and routines

`~/.claude/coderails-dashboard.json` holds both `buttons` (interactive,
user-triggered, defined by the merged `app/src/lib/config.ts`'s
`ButtonDef`) and `routines` (scheduled, artifact-gated, defined by this
package's `RoutineDef`) under one `DashboardConfig`. A `RoutineDef` names
either a `skillCommand` directly or a `buttonRef` pointing at an existing
`ButtonDef` — never both — and declares its `cadence`, `expectedArtifact`
(the artifact-gate contract the runner enforces after execution), and
`escalation` channels. See `src/config.ts` for the exact validation
rules.

## buildArgv: the one profile→flag mapping (imported, not owned here)

`buildArgv(btn: ButtonDef, input?: string): string[]` lives in
`skills/dashboard/app/src/lib/argv.ts` (merged via PR #25) and is the
only place a `ButtonDef.profile` is translated into `claude` CLI flags
anywhere in this contract. The obsidian plugin already imports it
directly (esbuild-bundled); this package's runner imports it the
same way. No consumer in this contract re-implements the profile→flag
mapping — `dashboard-lib` does not carry its own copy.

## Note on `tsconfig.json`'s `lib`

`test/schema-compat.test.ts` type-only-imports `IntentFile` from
`../../obsidian/src/exec`, which itself type-imports `ButtonItem`/
`PermissionProfile` from `obsidian/src/render.ts` — a file that uses DOM
types (`HTMLElement`, `document`). Because `tsc` type-checks the full
import graph reachable from the `include` set, this package's
`tsconfig.json` `lib` includes `"DOM"` alongside `"esnext"` purely to
satisfy that transitively-imported type; `dashboard-lib` itself has no
runtime DOM dependency and never emits code (`noEmit: true`).
