# @coderails/dashboard-lib

This package defines the consumer side of the intent queue and runner
contract. It owns the `Intent` schema. It also owns the `RoutineDef` and
`routines` section of `DashboardConfig`.

It imports `ButtonDef`, `PermissionProfile`, `loadConfig`, and the `buildArgv`
profile-to-flag mapping. These definitions live in
`skills/dashboard/app/src/lib/config.ts` and `argv.ts`. They merged in PR #25.

This README covers the schema contract only. See
[`docs/routines.md`](../docs/routines.md) for native on-demand execution.

## The queue seam is LIVE

As of PR #25, `skills/dashboard/obsidian/src/exec.ts` writes an intent file
for each button press. The path is
`~/.codex/coderails-dashboard/queue/<runId>.json`. The file matches this
package's `Intent` type:

```typescript
interface Intent {
  button: string;       // matches a ButtonDef.name or is the routine's own trigger name
  input?: string;       // optional freeform text, never parsed as a flag (see buildArgv)
  requestedAt: number;  // epoch-ms (Date.now()), NOT an ISO string
  source: "web" | "obsidian" | "cli" | string;
}
```

`parseIntent(raw: unknown): Intent` validates the input. It returns a typed
`Intent` or throws `IntentValidationError`. The compile-time test
`test/schema-compat.test.ts` checks this type against the Obsidian plugin's
`IntentFile` type on each build. It detects type drift between producer and
consumer.

`IntentFile.source` is `"obsidian"` on the wire in this PR #25 record.
Obsidian was the only merged producer then. The wider `Intent.source` type
allows future `"web"` and `"cli"` producers. It does not show that those
producers existed at the time.

**Interim producer behavior in the PR #25 record:** The Obsidian plugin
also runs `codex` directly after it writes the intent file. See
`obsidian/src/exec.ts` and its `pressButton` function. It does not wait for
the runner to claim the file. The contract below makes the runner the sole
executor. This loop did not change `app/` or `obsidian/` code.

## The runner is the sole executor (target state)

Only the runner (`skills/dashboard/runner`) may invoke the `codex` CLI for
an on-demand queued run. This is the target design rule for every surface
that uses the queue. The interim Obsidian behavior above did not meet it.

### Lifecycle

A queued intent file moves through these directories. The runner claims it
by atomic rename. It does not copy or edit the file in place.

1. `queue/<runId>.json` — A producer writes the file. The producer can be
   a web click, an Obsidian command, or a manual routine request. The file
   is not yet claimed. Producers create this directory with mode `0o700`. See
   `obsidian/src/main.ts` for the Obsidian case.
2. `processing/<runId>.json` — The runner claims the file with
   `fs.renameSync`. A rename on the same filesystem is atomic. Thus, two
   runner instances cannot claim the same file.
3. `archive/<runId>.json` — A successful run moves here. A configured
   retention rule can prune it.
4. `quarantine/<runId>.json` — A malformed file moves here when
   `parseIntent` fails. The sweep continues with the next file.

## Config: buttons and routines

`~/.codex/coderails-dashboard.json` holds `buttons` and `routines` in one
`DashboardConfig`. `ButtonDef` defines interactive buttons in
`app/src/lib/config.ts`. This package's `RoutineDef` defines on-demand,
artifact-gated routines. A routine names either a `skillCommand` or a
`buttonRef` to an existing button. It cannot name both. It also declares
`cadence`, `expectedArtifact`, and `escalation` channels. The runner checks
`expectedArtifact` after execution. See `src/config.ts` for validation rules.

## buildArgv: the one profile→flag mapping (imported, not owned here)

`buildArgv(btn: ButtonDef, input?: string): string[]` lives in
`skills/dashboard/app/src/lib/argv.ts`. It merged in PR #25. It is the
only profile-to-flag mapping in this contract. The Obsidian plugin imports
it directly through esbuild. This package's runner imports it too.
`dashboard-lib` does not carry another mapping.

## Note on `tsconfig.json`'s `lib`

`test/schema-compat.test.ts` imports the `IntentFile` type from
`../../obsidian/src/exec`. That file imports `ButtonItem` and
`PermissionProfile` types from `obsidian/src/render.ts`. The render file
uses DOM types such as `HTMLElement` and `document`. TypeScript checks the
full import graph. Thus, this package's `tsconfig.json` includes `"DOM"`
with `"esnext"`. `dashboard-lib` has no runtime DOM dependency. Its
`noEmit: true` setting prevents code output.
