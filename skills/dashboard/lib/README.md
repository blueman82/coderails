# @coderails/dashboard-lib

This package defines the consumer side of the intent queue contract. It owns the `Intent` schema and the `RoutineDef` and `routines` parts of `DashboardConfig`.

The base `ButtonDef`, `PermissionProfile`, `loadConfig`, and the `buildArgv` mapping to flags come from `skills/dashboard/app/src/lib/config.ts` and `argv.ts`. PR #25 merged those modules. This package imports their definitions.

This README covers the schema contract only. For how to actually stand
the system up on a new clone (`npm install` in this package and in
`skills/dashboard/runner`, where the dashboard's data directory comes
from, how to find the `claude` binary with `launchd`) see
[`docs/routines.md`](../../../docs/routines.md)'s Prerequisites section.

## The queue seam is LIVE

As of PR #25, `skills/dashboard/obsidian/src/exec.ts` writes
intent files to `~/.claude/coderails-dashboard/queue/<runId>.json` on
each button press. These files use this package's `Intent` type.

```typescript
interface Intent {
  button: string;       // Use a ButtonDef.name or the routine's own trigger name.
  input?: string;       // Optional freeform text. Do not parse it as a flag (see buildArgv).
  requestedAt: number;  // Epoch milliseconds from `Date.now()`, with no ISO string.
  source: "web" | "obsidian" | "cli" | string;
}
```

`parseIntent(raw: unknown): Intent` checks the input and gives a typed `Intent`. It throws `IntentValidationError` for malformed input. A compile-time
test (`test/schema-compat.test.ts`) type-checks this `Intent` type against
the obsidian plugin's own `IntentFile` type on each build, so producer
and consumer cannot silently drift apart.

The only merged producer uses the literal `"obsidian"` for `IntentFile.source`. The wider `Intent.source` union permits future producers (`"web"`, `"cli"`).

**Interim producer behavior.** The contract does not specify this behavior. The Obsidian plugin writes the intent file and then invokes `claude` directly. See `pressButton` in `obsidian/src/exec.ts`. It does not wait for the runner to claim and execute the intent.

This behavior is temporary until only the runner executes queued intents. This loop does not change it. See Global Constraints for the limits on `app/` and `obsidian/` changes.

## The runner is the sole executor (target state)

No surface other than the runner (`skills/dashboard/runner`) may
invoke the `claude` CLI for a queued or scheduled run. This design rule applies to each interface that uses this queue from this loop onward. The interim Obsidian behavior described above does not follow the rule.

### Lifecycle

A queued intent file moves only through the directories below. Use an atomic rename to claim it. Do not copy or edit it.

1. `queue/<runId>.json` — written by a producer (web click, Obsidian
   command, or scheduler). The runner has not claimed it.
   Producers make the directory with mode `0o700` (see `obsidian/src/main.ts`).
2. `processing/<runId>.json` — claimed by the runner through `fs.renameSync`.
   The atomicity of a same-filesystem rename is what prevents two runner
   instances from double-claiming the same intent.
3. On success: `archive/<runId>.json`. Remove it only if the configurable retention rule permits it.
4. On malformed input (fails `parseIntent`): `quarantine/<runId>.json` —
   the sweep continues with other files and does not crash-loop.

## Config: buttons and routines

`~/.claude/coderails-dashboard.json` holds `buttons` and `routines` in one `DashboardConfig`. Buttons are interactive and start when the user selects them. See `ButtonDef` in the merged `app/src/lib/config.ts`. See this package’s `RoutineDef` for the schedule and artifact gate.

A `RoutineDef` specifies one of two fields: a `skillCommand` or a `buttonRef` that points to an existing `ButtonDef`. It also specifies `cadence`, `expectedArtifact`, and `escalation` channels. The runner applies the artifact gate after execution. See `src/config.ts` for the validation rules.

## buildArgv: the one profile→flag mapping (imported, not owned here)

`buildArgv(btn: ButtonDef, input?: string): string[]` is in `skills/dashboard/app/src/lib/argv.ts`, which PR #25 merged. It is the only function in this contract that maps a `ButtonDef.profile` to `claude` CLI flags.

The Obsidian plugin and this package’s runner import it directly. The Obsidian plugin bundles it with esbuild. Consumers share the mapping. `dashboard-lib` does not have a copy.

## Note on `tsconfig.json`'s `lib`

`test/schema-compat.test.ts` type-only-imports `IntentFile` from
`../../obsidian/src/exec`, which itself type-imports `ButtonItem`/
`PermissionProfile` from `obsidian/src/render.ts` — a file that uses DOM
types (`HTMLElement`, `document`).

Because `tsc` type-checks the full
import graph reachable from the `include` set, this package's
`tsconfig.json` `lib` includes `"DOM"` alongside `"esnext"` purely to
satisfy that transitively imported type. `dashboard-lib` has no runtime DOM dependency and writes no output code (`noEmit: true`).
