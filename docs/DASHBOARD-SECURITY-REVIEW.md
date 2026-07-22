# Dashboard security review

## Scope and result

This review covers `skills/dashboard/` — the coderails observability dashboard, its queue/runner architecture, and the routines that run through it. It was performed by two independent reviewers plus the orchestrator, reviewed 2026-07-22.

Six findings resulted. All six are severity Low. None were deferred. No finding crosses a privilege boundary — every one is a same-user, local-process concern.

## Defences that held

These were tested during the review and found sound. They are verified at source, not assumed.

- **Flag injection into the spawned `claude` CLI is not defeatable.** `argv.ts` spawns via an argv array (no shell), rejects any input whose trimmed value starts with `-`, inserts a `--` end-of-options sentinel, and concatenates input into a single prompt string — so input can never split into new argv elements.
- **DNS rebinding is defended and explicitly tested.** `test/requestGuard.test.ts` covers `Host: evil.com`, the suffix attack `192.168.50.140.evil.com`, a mismatched Origin with a matching Host, and an off-by-one LAN IP.
- **Path traversal in the run-output route is closed.** `runId` is format-validated and used only as a lookup key. The file read uses the stored record's own `outputPath`, never a joined request value.
- **The exec lock in `api/run/route.ts` has no TOCTOU window.** `writeFileSync` with flag `"wx"` makes the exclusive create the check itself. Stale locks unlink and retry exactly once.
- **osascript escalation (`runner/src/escalate.ts:36`) cannot inject into AppleScript source.** Title and message are passed as trailing argv via `on run argv`, never interpolated into the script text.
- **The approve-to-build path (`run-builder.sh`) re-validates on the way in.** The hash is checked against a recomputed `jq -S -c` digest, symlinks are rejected, and `PROPOSED_NAME` is charset-gated before it can become a branch name.
- **SSE framing (`api/events/route.ts:13-15`) cannot be forged from run output.** Every payload goes through `JSON.stringify`, so run output cannot inject an `event:` line.
- **Read-only routine sessions cannot escalate to the queue.** `profileFlags` gives them `--allowedTools Read Grep Glob` — no Write, no Bash.

## Threat model

Every finding below is same-user, local-process. Nothing crosses a privilege boundary.

`~/.claude` and `~/.claude/coderails-dashboard/` are both `drwx------`. Any process able to write into those directories can already run `claude --dangerously-skip-permissions` directly — routing through the queue gains an attacker nothing they don't already have.

The review also considered an internet-exposed deployment model. The dashboard is currently LAN-bound, not internet-exposed. The run token is embedded in page HTML, which means internet exposure is not currently safe — but this is a design property of the current deployment model, not one of the six findings below.

## Findings

### Finding 1: Queue path skips the `inputAllowed` authorization check

**Severity:** Low, local-process.

**Threat model:** A local process able to drop a file into the queue directory.

**Problem:** `api/run/route.ts:163` rejects input unless `button.inputAllowed` is set. `runner/src/sweep.ts:227` calls `buildArgv(button, intent.input)` with no equivalent check.

**Vulnerability:** `lib/src/intent.ts:32-34` accepts any string as `input`. Live config has three bypass buttons — `loop-retro-promotion`, `inbox-brief`, `sync-docs` — none of which declares `inputAllowed`. A queue file can carry input the route handler would have rejected.

**Impact:** A local process dropping a queue file gets arbitrary prompt text appended to a bypass-profile command. This is prompt control, not argv control: `buildArgv`'s dash-rejection and `--` end-of-options sentinel (see Defences above) prevent the appended text from being parsed as flags.

**Resolution:** Quarantine the intent in `sweep.ts` before `buildArgv` when input is present and `inputAllowed` is false, mirroring the check already in `route.ts`.

**Effect after implementation:** The queue path and the HTTP path enforce the same authorization rule. A queue file carrying disallowed input is quarantined rather than executed.

**Deferred:** No.

### Finding 2: `entry.hash` path traversal

**Severity:** Low, local-process.

**Threat model:** A local process able to place a file the queue will pick up.

**Problem:** `lib/collect/queueActions.ts:89` returned `{...parsed, status}` — the spread carried the file's own `hash` field, not the validated parameter — and `lib/build/spawn.ts:130` did `join(buildsDir, entry.hash)`.

**Vulnerability:** A crafted `hash` field reaches a `join()` call unvalidated.

**Impact:** A file-write primitive into an arbitrary directory, triggered on owner Approve. Not code execution: `run-builder.sh` re-validates the hash against a recomputed digest and fails closed (see Defences above).

**Resolution:** Return the validated `hash` at the source in `queueActions.ts`, plus pre-join regex validation in `spawn.ts` as defence in depth.

**Effect after implementation:** The value used in `join(buildsDir, entry.hash)` is the same value that was validated, not an unvalidated pass-through from the file.

**Deferred:** No.

### Finding 3: Config loader schema validation

**Severity:** Low, local-process.

**Threat model:** A malformed or crafted `workflow.config.yaml`.

**Problem:** `lib/config.ts:56` iterated `data.buttons` with no array check — a missing key throws a raw `TypeError` — and validated neither type nor charset for `name`, `label`, or `command`.

**Vulnerability:** `name` has a real sink: `api/run/route.ts:76-78` does `join(locksDir, name + ".lock")` with no charset constraint on `name`.

**Impact:** An unvalidated `name` could influence the lock file path.

**Resolution:** Added an array guard on `data.buttons`, string-type checks on `name`/`label`/`command`, and constrained `name` to `/^[a-z0-9][a-z0-9._-]{0,63}$/`.

A `cwd` allowlist was considered and explicitly not recommended: it buys nothing against a same-user attacker (who can already edit the config) and costs usability.

**Effect after implementation:** A malformed config fails validation with a clear error instead of throwing a raw `TypeError` or admitting an unconstrained `name` into a path join.

**Deferred:** No.

### Finding 4: Inconsistent directory and file permissions

**Severity:** Low, local-process.

**Threat model:** Defence-in-depth only — relevant if the outer directory permission were ever weakened.

**Problem:** `archive/`, `processing/`, `quarantine/`, `locks/`, and `runs/` are 0755, and `runs/*.log` is 0644, while `queue/`, `approvals/`, `builds/`, and `routines/` are 0700.

**Vulnerability:** Root cause is that `mkdirSync`'s mode argument is a no-op on an already-existing directory, and these directories were first created without an explicit mode under a 0022 umask — at `runlog.ts:44` and `api/run/route.ts:177,184` and `build/spawn.ts:132`. `obsidian/src/main.ts:134` writes intent files with no explicit mode while `:133` creates the parent directory 0700.

**Impact:** None today. The 0700 parent (`~/.claude/coderails-dashboard/`) makes these inner permissions unreachable from outside the owning user regardless.

**Resolution:** Explicit modes set at creation, plus an opportunistic chmod-tighten so existing live installs converge to the same permissions on next write.

**Effect after implementation:** New installs get consistent 0700/0600 permissions throughout; existing installs tighten opportunistically without a migration step.

**Deferred:** No.

### Finding 5: `escapesRoot` skips containment for templates lacking a `{vault}` token

**Severity:** Low, local-process. Lowest priority of the six.

**Threat model:** Config-authored `artifactPath` templates, same trust tier as code.

**Problem:** `runner/src/artifactGate.ts:41-47` returns `false` (meaning: no containment violation) when the template contains no `{vault}` token, trusting the config-authored path as-is.

**Vulnerability:** A routine's `artifactPath` template can point anywhere on disk if it omits `{vault}`.

**Impact:** None today — routine config is already the same trust tier as code; anyone who can add a routine can already write arbitrary code that runs under the same user.

**Resolution:** Documentation only, no code change. The routine-authoring docs now note that `artifactPath` is trusted input, not sandboxed.

**Effect after implementation:** Routine authors are told explicitly that `artifactPath` is not contained when `{vault}` is absent, so they don't rely on an isolation guarantee that doesn't exist.

**Deferred:** No, but lowest priority of the six.

### Finding 6: Run-token comparison is not timing-safe

**Severity:** Low, both threat models (local-process and the considered internet-exposed model).

**Threat model:** Both same-user local and a hypothetical remote attacker measuring response timing.

**Problem:** Token comparison used `!==` at `api/run/route.ts:149`, `api/run/output/route.ts:77`, and `api/queue/route.ts:66`.

**Vulnerability:** `!==` is not constant-time, so comparison duration can in principle leak information about how many leading bytes matched.

**Impact:** The token is `randomBytes(32)` — 256 bits (`lib/runlog.ts:157`) — and is already embedded in the page HTML for anyone able to load the page. A remote timing attack against 256 bits of entropy is not the weak link in this system; fixed for hygiene, not because it was an exploitable gap in practice.

**Resolution:** A shared `crypto.timingSafeEqual` helper, handling the length-mismatch case explicitly (`timingSafeEqual` throws on unequal-length buffers rather than returning false).

**Effect after implementation:** All three comparison sites use the same constant-time helper.

**Deferred:** No.

## Deferred items

None. Every one of the six findings had a straightforward code or documentation fix requiring no product decision.
