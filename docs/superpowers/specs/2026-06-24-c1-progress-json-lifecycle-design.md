# Spec C1 — progress.json lifecycle + presence/ownership guard

**Date:** 2026-06-24
**Status:** Design approved (brainstorming + planning-sequence complete); pending writing-plans
**Targets:** new `hooks/scripts/loop_state_guard.sh`, new shared path helper, `hooks/hooks.json`, `skills/agentic-loop/SKILL.md`
**Part of:** the agentic-loop improvement decomposition. Spec C was split into **C1** (this — make progress.json reliable) and **C2** (the anti-stall hook that reads it). Sequence: A (done) → **C1** → C2 → B → D.

---

## Problem

`progress.json` is the agentic-loop skill's durable loop-state artifact, but it is an
**unenforced convention**. The skill says "maintain a single progress.json," yet
nothing guarantees it exists, is current, or is torn down. Two downstream consumers
depend on it being trustworthy:

- **Spec A's Phase 13 counter** audits disposition violations against the
  `progress.json` record — and explicitly treats "no record found" as an audit
  failure. That audit is meaningless if the file is unreliably present.
- **Spec C2** (the anti-stall hook) reads the envelope class and loop status from
  `progress.json` to decide whether a stop is an unauthorised stall.

C1 makes the file reliable: when an agentic loop is active in a session, a
session-owned `progress.json` reliably exists at a deterministic location,
mechanically enforced by a Stop hook.

## Goal / success criterion

When the agentic-loop skill is active in a session, the orchestrator cannot stop
without a session-owned `progress.json` present at the resolved path. Normal
(non-loop) sessions are never affected. Phase 13 and C2 can trust the file's
presence and ownership.

## Scope boundary (what C1 does and does NOT enforce)

C1 enforces **presence + ownership only**:
- *Presence* — a loop is active ⇒ the file exists.
- *Ownership* — the file is stamped with the current `session_id`.

C1 deliberately does **not** try to detect "stale despite present" (a file that
exists and is session-owned but whose content has gone out of date). A forgotten
teardown leaves a `present + owned + in-progress` file, which C1 correctly does
**not** block — presence is satisfied. The over-fire risk that a forgotten teardown
poses lands on **C2** (which will additionally require `status != complete` + fresh
activity). Keeping C1 to presence+ownership is what makes it a thin, reliable
foundation rather than a freshness oracle it cannot honestly be.

## Design decisions (brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Location | `~/.claude/agentic-loop/<cwd-hash>/progress.json` — outside repo, cwd-keyed | No base pollution (Phase 2.5 principle); per-project; survives session restart/compaction |
| Ownership / staleness | `session_id` stamped in file content; hook compares to its payload `session_id` | Survives compaction (stable id); cross-session safe (mismatch ⇒ not mine); resume = deliberate adoption |
| Loop-active signal | structured `jq` match on a Skill `tool_use` with `input.skill == "coderails:agentic-loop"` | Precise opt-in marker; captures TeamCreate loops transitively (skill triggers on TeamCreate); silent on sessions that merely discuss the skill |
| Guard strength | block immediately (exit 2) on absent / ownership-mismatch while loop active | Mechanical guarantee of presence; the repo's hook philosophy |

## Design (hardened by planning-sequence)

### Path authority — the model NEVER computes the path

The single most important fix from the planning-sequence: a model cannot reliably
reproduce a `cwd-hash`, so the model must never derive the path. The **hook is the
sole path authority**:

- A shared helper script (`hooks/scripts/lib/agentic_loop_path.sh`) computes and
  prints the absolute `progress.json` path from `$PWD` (or a passed cwd). It is the
  single source of truth for the path, called by **both** the guard hook (reader)
  and the orchestrator (writer, via a `Bash` call).
- When the guard blocks, its message includes the **resolved absolute path**, so the
  model writes the stub to exactly the path the hook will read next turn. The model
  copies a path; it never computes one.

This dissolves the otherwise-100% deadlock where the model writes to a wrongly-hashed
path the hook never inspects.

### Loop-active detection — structured, never textual

Detection is a `jq` query over this session's transcript for an assistant
`tool_use` entry with `name == "Skill"` and `input.skill == "coderails:agentic-loop"`.
(Verified: skill invocations appear in the transcript as
`{"name":"Skill","input":{"skill":"coderails:agentic-loop"}}`; a session that merely
discusses or edits the skill — like the one that designed this spec — never produces
that `tool_use`, so the detector stays silent.) A text grep for "agentic-loop" is
explicitly forbidden: it would tyrannise the maintainers who work on the skill.

### Lifecycle contract (couples edits to `skills/agentic-loop/SKILL.md`)

- **Stub-first.** The literal first action on agentic-loop skill-load — before
  Phase -1 — is to write a `progress.json` stub at the helper-script path:
  `{ schema_version, session_id, status: "initialising", created, authorising_prompt_raw }`.
  This guarantees the file exists before the first stop, so a compliant loop never
  trips the block; the block degrades to a backstop for a skipped stub.
- **Enrich at Phase 0** — record the envelope verbatim; `status: "in-progress"`.
- **Update at each phase boundary** — current phase, work-unit states, Spec A's
  disposition fields, Phase 13 counters, `last_updated`.
- **Teardown at Phase 13** — `status: "complete"`, plus a `completed_marker` (see
  recency).

### Recency re-arming — a second loop isn't masked by a stale `complete`

The agentic-loop skill explicitly supports multiple loops in one long session. A
prior loop's `status: "complete"` must not silence the guard for a later loop. The
file records a `completed_marker` (the transcript position / count of
agentic-loop invocations at completion time). The guard enforces when the **latest**
agentic-loop `tool_use` in the transcript is **newer** than the `completed_marker` —
i.e. a new loop started after the prior one finished. Starting a new loop also
overwrites the stub (`status` back to `in-progress`), but the guard does not rely on
that alone — recency is the authority.

### The guard hook — `hooks/scripts/loop_state_guard.sh` (Stop)

Follows the `check_verify_loop.sh` idiom: read payload from stdin via `jq`, numbered
skip-gates that exit early (cheapest first), block via `exit 2` + stderr, append a
`key=value` line to `$CLAUDE_DISCIPLINE_LOG`.

Gates (first match decides):
1. **No transcript** in payload → allow.
2. **Loop-guard:** `stop_hook_active == true` (already blocked this turn) → allow.
3. **Not a loop:** no agentic-loop Skill `tool_use` in the transcript → allow. (The
   opt-in marker is absent; no discipline in force.)
4. **Genuinely complete:** `progress.json` exists, `status == "complete"`, and the
   latest agentic-loop invocation is **not** newer than `completed_marker` → allow
   (the loop is done; a stale invocation in history must not re-arm).
5. **Present & owned & active:** file exists, `session_id` matches payload, not
   complete → allow (presence + ownership satisfied).
6. **BLOCK (exit 2):**
   - file **absent** → "Agentic loop active but no progress.json. Create it at
     `<resolved-absolute-path>` (stub schema: …) before stopping."
   - file present but **`session_id` mismatch** → "progress.json at `<path>` belongs
     to session `<X>`. Adopt this loop (re-stamp `session_id`) or reinitialise."

Resolve `<resolved-absolute-path>` by calling the shared helper. Retry the
transcript read with backoff for the flush race, exactly as `check_verify_loop` does.

### Registration — `hooks/hooks.json`

Add `loop_state_guard.sh` to the existing `Stop` array (alongside
`check_confidence_labels.sh` and `check_verify_loop.sh`), `timeout: 15`.

### Schema additions (atop Spec A's fields)

`schema_version`, `session_id`, `status` (`initialising` | `in-progress` |
`complete`), `created`, `last_updated`, `completed_marker`.

## Files touched

- **Create** `hooks/scripts/loop_state_guard.sh` — the guard.
- **Create** `hooks/scripts/lib/agentic_loop_path.sh` — shared path authority,
  called by the hook and (via Bash) the orchestrator.
- **Modify** `hooks/hooks.json` — register the Stop hook.
- **Modify** `skills/agentic-loop/SKILL.md` — stub-first Phase -1 rule, lifecycle +
  teardown rules, recency marker, and the Context-window-persistence schema doc.
- **Modify** `install.sh` — add both new scripts to the chmod list.

`install.sh` arms scripts via an **explicit hardcoded list**, not a glob (verified:
lines 322–325; the list already names `scripts/lib/git-common.sh` individually, so
`lib/` scripts are not auto-covered). Both new scripts —
`hooks/scripts/loop_state_guard.sh` and `hooks/scripts/lib/agentic_loop_path.sh` —
**must be appended to that `for script in …` list**, or they ship without the
executable bit and the hook silently fails to run. The hook is registered in the
plugin's `hooks.json` (not the user's `settings.json`), so `uninstall.sh` needs no
change.

## Planning-sequence findings folded in

- **Path-derivation deadlock (critical):** model never computes the path → hook is
  sole path authority + shared helper + resolved path in the block message.
- **Self-mention poisoning:** structured `jq` `tool_use` detection, never text (verified
  silent on a discuss-only session).
- **Startup-block irony:** stub-first contract makes a compliant loop never trip the
  block; it degrades to a backstop.
- **The "complete" mask:** recency re-arming, not `status` alone.

## Known limitations

- **Honest boundary (same as the existing hooks).** C1 enforces presence +
  ownership; it cannot force the file's *content* to be accurate or current — a model
  could write a stub and never enrich it. The guarantee is "the file exists and is
  mine," not "the file is faithfully maintained." This is the same limit
  `check_verify_loop.sh` documents ("forces declaration, cannot force honesty").
- **Forgotten within-session teardown** leaves a benign `present+owned+in-progress`
  file (C1 does not block); the over-fire it could cause is C2's concern.
- **Concurrent same-cwd sessions** share a path (cwd-keying). The session-stamp makes
  the second session see a mismatch and be told to adopt/reinitialise — which could
  thrash if two loops genuinely run concurrently in one repo. Rare; documented, not
  designed against in C1.

## Testing

- `bash -n` on both new scripts (the repo's test gate).
- Behavioural assertions by feeding synthetic Stop payloads to `loop_state_guard.sh`
  (stdin JSON with a `transcript_path` pointing at a fixture `.jsonl`): assert
  `exit 0` when no agentic-loop invocation is present; `exit 2` when a loop is active
  and the file is absent; `exit 2` on `session_id` mismatch; `exit 0` when present +
  owned + in-progress; `exit 0` when `complete` and no newer invocation; `exit 2`
  when `complete` but a newer invocation re-arms. Fixtures live under a temp dir, not
  the repo tree.

## Sequencing

A (clean-migration discipline) — **DONE**, merged `#12`.
→ **C1** (this) — make progress.json reliable.
→ **C2** — thin declaration-based anti-stall hook reading C1's reliable file.
→ **B** — slim the skill.
→ **D** — superpowers construction-discipline seam (sonnet-only).
