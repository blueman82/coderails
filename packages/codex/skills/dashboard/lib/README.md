# @coderails/dashboard-lib

This package is the authoritative source for the consumer parts of the intent queue and runner contract.
These parts are the `Intent` schema and the `RoutineDef` and `routines` section of `DashboardConfig`.
The base `ButtonDef`, `PermissionProfile`, and `loadConfig` come from `skills/dashboard/app/src/lib/config.ts`.
The `buildArgv` mapping from permission settings to flags comes from `argv.ts`.
Those modules merged through PR #25. This package imports them and has no duplicate implementation.

This README gives the schema contract only. See [`docs/routines.md`](../docs/routines.md) for native runs on demand.

## The queue seam is LIVE

As of PR #25, `skills/dashboard/obsidian/src/exec.ts` writes intent files to `~/.codex/coderails-dashboard/queue/<runId>.json` on each button click.
The files conform to this package's `Intent` type:

```typescript
interface Intent {
  button: string;       // the ButtonDef.name or the routine's own trigger name
  input?: string;       // optional freeform text. buildArgv does not parse it as a flag
  requestedAt: number;  // epoch-ms (`Date.now()`), NOT an ISO string
  source: "web" | "obsidian" | "cli" | string;
}
```

`parseIntent(raw: unknown): Intent` checks the input and gives a typed `Intent`.
If the input is malformed, it throws `IntentValidationError`.
On each build, `test/schema-compat.test.ts` checks `Intent` against the Obsidian plugin's `IntentFile` type.
This compile-time test prevents silent differences between producer and consumer.

`IntentFile.source` uses only the literal `"obsidian"` on the wire because Obsidian is the only merged producer.
The wider `Intent.source` union has values for future producers (`"web"`, `"cli"`). There are no such producers today.

**Interim producer behavior.** The Obsidian plugin runs `codex` directly after it writes the intent file.
See `pressButton` in `obsidian/src/exec.ts`. It does not wait for the runner to claim and run the queued intent.
This interim behavior is out of scope for this contract and this loop.
See Global Constraints for the scope limits on `app/` and `obsidian/` code.

## The runner is the sole executor (target state)

Only the runner (`skills/dashboard/runner`) can invoke the `codex` CLI for an on-demand queued run.
This permanent design rule applies to each surface that uses the queue from this loop forward.
The Obsidian plugin's interim behavior above does not follow the rule.

### Lifecycle

A queued intent file moves through these directories. The runner claims it by an atomic rename.
Do not copy the file or edit it in its current directory.

1. `queue/<runId>.json`. A producer writes the file for a web click, Obsidian command, or manual run.
   The runner has not claimed it. Producers make the directory with mode `0o700` (see `obsidian/src/main.ts`).

2. `processing/<runId>.json`. The runner uses `fs.renameSync` to claim the file.
   The rename on the same filesystem is atomic, so two runner instances cannot claim the same intent.

3. On success, the runner moves the file to `archive/<runId>.json`.
   Only the configurable retention prune can remove it.

4. If `parseIntent` rejects malformed input, the runner moves the file to `quarantine/<runId>.json`.
   The sweep continues without a crash loop.

## Config: buttons and routines

`~/.codex/coderails-dashboard.json` holds `buttons` and `routines` in one `DashboardConfig`.
The merged `ButtonDef` in `app/src/lib/config.ts` defines interactive `buttons` that the user triggers.
This package's `RoutineDef` defines `routines` that run on demand with an artifact gate.

A `RoutineDef` names only one of `skillCommand` or `buttonRef`.
A `buttonRef` points to an existing `ButtonDef`.
The `RoutineDef` also declares `cadence`, `expectedArtifact`, and `escalation` channels.
After the run, the runner checks `expectedArtifact` as the artifact gate.
See `src/config.ts` for the validation rules.

## buildArgv: the one profile→flag mapping (imported, not owned here)

`buildArgv(btn: ButtonDef, input?: string): string[]` lives in `skills/dashboard/app/src/lib/argv.ts` (merged through PR #25).
Only this function maps `ButtonDef.profile` to `codex` CLI flags in this contract.
The Obsidian plugin imports it directly and bundles it with esbuild. This package's runner imports it in the same manner.
Consumers use that mapping. `dashboard-lib` has no copy of it.

## Note on `tsconfig.json`'s `lib`

`test/schema-compat.test.ts` imports only the `IntentFile` type from `../../obsidian/src/exec`.
That module imports the `ButtonItem` and `PermissionProfile` types from `obsidian/src/render.ts`, which uses DOM types (`HTMLElement`, `document`).
`tsc` type-checks all imports reachable from the `include` set.
This package's `tsconfig.json` `lib` includes `"DOM"` with `"esnext"` only to satisfy that indirect type import.
`dashboard-lib` has no runtime DOM dependency or code output (`noEmit: true`).
