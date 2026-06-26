# Subagent Enforcement & Gate Hardening — Design

**Date:** 2026-06-26
**Status:** Draft (awaiting review)
**Subject:** Harden coderails so its discipline cannot be bypassed or ignored — whether work runs in the main agent or a subagent.

## Problem

coderails' only mechanical enforcement is its hooks. Everything else (commands, skills, instructions) is advisory. An audit of `hooks.json` + all 11 hook scripts found two classes of gap:

1. **A whole execution mode is unguarded.** The four `Stop`-family scripts (`check_confidence_labels`, `check_verify_loop`, `loop_state_guard`, `loop_stall_guard`) fire only on the *main agent's* `Stop`. Subagent completion is a separate `SubagentStop` event that coderails does not hook. A subagent can self-report unverified claims and the main agent relays them, unchecked.
2. **Several existing gates are individually defeatable or have coverage holes.**

This spec closes the closeable gaps and documents the honest ceilings of the rest.

## Threat model

The adversary is a future Claude instance (or a rushed session) that treats coderails as friction and looks for the path of least resistance — plus a sceptic who will call soft checks theatre. Success = the discipline holds for delegated work, and the casual bypass of each gate is closed, with residual limits documented rather than papered over.

## Keystone risk (drives everything)

Every subagent fix rests on one unverified runtime fact: **does `SubagentStop` deliver the subagent transcript, and does `PreToolUse` fire inside subagents?** The default failure shape is *silent success* — every Stop script `exit 0`s on a missing/mismatched transcript, so a wrongly-wired `SubagentStop` hook looks installed (it's in `hooks.json`) while enforcing nothing.

**Therefore Phase 0 is a live hook-payload probe, and no subagent gate is considered done until a test proves it returns `exit 2` on a non-compliant subagent.** "No error" is not evidence of enforcement.

## Scope

**In scope (proceed):**

| # | Item | Severity |
|---|---|---|
| 1 | Wire discipline to `SubagentStop` — **content checks only** | 🔴 HIGH |
| 2 | `enforce_pr_workflow`: per-PR / consume-on-use review, not session-wide | 🔴 HIGH |
| 3 | Branch-aware Bash arm: in-place writes to source on main | 🔴 HIGH |
| 4 | Extend `destructive_bash_gate` blocklist families | 🔴 HIGH |
| 5 | `no_edit_on_main`: invert code arm to an allowlist | 🟠 MED |
| 6 | `enforce_pr_workflow`: parse positional `git push … main` | 🟠 MED |
| 7 | `check_verify_loop`: enforce DNV-tagging whenever a DNV section exists | 🟠 MED |

**Dropped (Red Team earned the cut):**

- **#8 evidence-token confidence labels** — a presence-check cannot exceed presence. A more-trusted-but-equally-dishonest label is negative value. Not parked; cut.

**Accept and document (honest ceilings, no code):**

- **#9** wiki/workflow sequence past merge — at best a non-blocking `PostToolUse` nudge; can't be forced.
- **#10** Stop-loop guards block at most once per turn — the infinite-loop safety valve; keep.
- **#11** TDD not test-first — gating it is high-false-positive; skip.
- **#12** `--dry-run`/`--help` loose substring — minor; tighten only if cheap alongside #6.
- **#13** skill invocation / ask-on-ambiguity / verify-memory — structurally unenforceable by any hook.
- **#14** subagent bootstrap — **no `SubagentStart` event exists.** The `using-coderails` "1% rule" cannot reach a subagent via hooks; it must live in the subagent/agent-definition system prompt. Structural ceiling.

## Design

### Phase 0 — Probe (keystone, blocks all subagent work)

Run a real subagent that (a) makes a Bash tool call and (b) finishes with a substantive, unlabelled message. Capture the actual hook payloads. Confirm:
- `PreToolUse` fires for the subagent's Bash call (field `tool_input.command` present).
- `SubagentStop` fires and carries a `transcript_path` whose last assistant text is readable by the existing `dc_stable_text` extractor.

Encode the result as a test fixture (a captured `SubagentStop` payload) so the suite asserts real behaviour, not assumptions. **If the probe shows `SubagentStop` lacks a usable transcript, item #1 is infeasible and this spec is revised before any further work.**

### Item 1 — `SubagentStop` discipline (content checks only)

Register **only** `check_confidence_labels` and `check_verify_loop` on `SubagentStop`. **Not** the two loop guards: they key off the main agent's agentic-loop invocation count and a main-owned `progress.json`, which a subagent transcript never has — they would either no-op or misfire. (`loop_state_guard`/`loop_stall_guard` already `exit 0` when invocations = 0, so leaving them off `SubagentStop` is also the safe default.)

A subagent has no `using-coderails` bootstrap (#14), but the block's stderr message *is fed back to the subagent as the reason*, so it can self-correct from the message alone — no bootstrap dependency.

Verify each script's transcript extraction works against the real `SubagentStop` payload shape (from Phase 0); adapt only if fields differ.

**Test:** a non-compliant subagent transcript → `exit 2`; a compliant one → `exit 0`.
**Outcome:** delegated work meets the same label/DNV standard as main-agent work.

### Item 2 — per-PR / consume-on-use review

`enforce_pr_workflow` currently counts *any* `review-pr` invocation in the session, so one review clears every later merge. Change:
- `gh pr merge <N>` → require a `review-pr` invocation referencing `<N>`.
- local `git merge` (no PR number) → "review-pr ran since the last merge" (consume-on-use), not "ever ran."

**Test:** review PR #1, then attempt to merge PR #2 unreviewed → blocked.
**Outcome:** one review buys one merge.

### Item 3 — branch-aware in-Bash edit gate

Add an arm to a Bash `PreToolUse` hook that denies in-place writes/redirects into gated source extensions (`sed -i`, `tee`, `>`/`>>`, `cat >`) when on main/master.

**Test:** `sed -i … file.py` on main → blocked; same on a feature branch → allowed.
**Outcome:** "no source edits on main" holds regardless of which tool writes.

### Item 4 — extend destructive blocklist

Add the missing families to `destructive_bash_gate`: `git clean -f[dx]`, `find … -delete`, `truncate`, `shred`.

**Test:** each new pattern → blocked; benign lookalikes (`git cleanup`, `findings`) → allowed.
**Outcome:** common destructive forms caught. **Documented residual:** still a blocklist — an action wrapped inside a script Claude writes then executes is invisible to the matcher (the "wrap-and-run" boundary). This is accepted, not closed.

### Item 5 — `no_edit_on_main` allowlist inversion

Invert the code arm: on main/master, block edits to *everything* except an explicit allowlist of doc/config extensions. Preserve the PR #52 cross-repo behaviour (decisions key off the file's own repo) and the plugin-markdown nuance.

**Test:** `.rs`/`.java`/`.sh` on main → blocked; allowlisted `.md`/config → allowed; PR #52 cross-repo cases still pass.
**Outcome:** language-agnostic; new languages protected by default.

### Item 6 — positional `git push … main`

Parse positional `git push` args for a `main`/`master` destination, not just colon-refspecs. Tighten the `--dry-run`/`--help` match to word-boundary flags while in this file (#12, cheap rider).

**Test:** `git push origin main` from a feature branch → blocked; `git push origin feature` → allowed.
**Outcome:** direct-to-main push gated in both refspec and positional forms.

### Item 7 — DNV-tag check independent of edits

`check_verify_loop` currently `exit 0`s when no file was edited this turn, so claim-heavy no-edit turns escape. Change: if a `## Did Not Verify` section is present, enforce tagging *regardless* of edits. Keep the file-count condition only for *requiring* a DNV section (so pure-chat turns aren't nagged).

**Test:** a no-edit turn with an untagged DNV bullet → blocked; a no-edit turn with no DNV section → allowed.
**Outcome:** tag discipline applies wherever a DNV section appears.

## Testing strategy

- Every item ships with a test in `hooks/scripts/tests/` following the existing `*.test.sh` pattern; `run_all.sh` stays green.
- TDD: write the failing test first, watch it fail for the right reason, then implement (per the `test-driven-development` skill).
- Phase 0's captured payload becomes a committed fixture so subagent tests assert against real shapes.
- **Each `exit 2`-path test must assert the block actually fired**, not merely that the script ran — this is the explicit defence against the silent-no-op failure mode.

## Out of scope

The "accept and document" items (#9–#14). They get a short note in `CLAUDE.md`/`REFERENCE.md` recording the honest ceiling, no behavioural change.

## Sequencing note

Phase 0 gates Items 1. Items 2–7 are independent of the probe and of each other; they can land as separate PRs in any order. Items 6 and the #12 rider share `enforce_pr_workflow.sh`, so land them together.
