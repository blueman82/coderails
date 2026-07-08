# Coderails Codebase Review — Changes, Additions, and Removals

**Date:** 2026-06-25
**Scope:** Full codebase review including hooks, skills, commands, scripts, and wiki subsystem

---

## Overview

`coderails` is a single Claude Code plugin (v1.1.0) by Gary Harrison — a merged successor to two former separate plugins (`workflow-tools` and `claude-guardrails`). It ships as a zip, installs via `install.sh` + `/plugin install`, and bundles three core capabilities:

1. **Workflow commands** — `prep → push → merge → wiki` chain
2. **Skills** — agentic-loop, planning-sequence, premortem, handoff, improve-prompt, test-driven-development, writing-plans, and the wiki subsystem
3. **Hooks** — mechanical enforcement for confidence labels, DNV verification, loop state/stall guards, destructive bash, and test gates

This document identifies 8 proposed changes: 2 removals, 3 additions, and 3 modifications — each with rationale grounded in the codebase's own design invariants and failure logs.

---

## 1. REMOVE: The Wiki Subsystem

**Affected:** `skills/wiki-init/`, `skills/wiki-ingest/`, `skills/wiki-lint/`, `skills/wiki-query/`, `AGENTS.md` (wiki schema portions), `templates/`, `/workflow` Phase 5 wiki steps

**Why:**

The wiki is a self-contained knowledge-management system embedded inside a plugin whose mission is "Git workflow + agentic discipline." It has its own AGENTS.md schema, its own Obsidian vault, its own worktree/PR flow, four dedicated skills, bundled assets including a 3.6MB Marp plugin, cmake/matplotlib/qmd dependencies, and a vault creation ritual. These are two different products sharing one namespace.

**The cost it imposes on coderails:**

- **Cognitive load spread across 4 skills + AGENTS.md + templates.** The wiki-ingest skill alone covers git worktrees for the *wiki vault* (a separate repo!), inbox files, PR ingestion — all orthogonal to coderails' core workflow (which manages worktrees for the *code repo*).
- **`/workflow` Phase 5** bakes wiki-ingest and wiki-lint into the canonical merge path. If wiki isn't set up, it no-ops — but the connector is still there, coupling two systems that don't need to be coupled.
- **The AGENTS.md at repo root** is really the wiki's schema file, not coderails'. It describes wiki vault structure, page types, frontmatter conventions, workflows — none of which matter to someone using coderails for its workflow/agentic/discipline features.
- **The wiki-init skill** bundles Obsidian config, a Marp plugin, and a vault creation ritual. This is a whole separate product.

**Proposed action:** Extract the wiki subsystem into its own plugin (e.g., `llm-wiki`). It's genuinely useful, general-purpose, and doesn't depend on coderails' hooks, commands, or agentic-loop. Remove the 4 wiki skills, the `/wiki-*` phase from `/workflow`, and the wiki-specific portions of AGENTS.md.

---

## 2. REMOVE: Pre-Filled `starter-memory/` Content

**Affected:** `starter-memory/` directory, `templates/failure_log.md`

**Why:**

The installer seeds four feedback memories with `type: feedback` frontmatter and `templates/failure_log.md` with 3 pre-filled rows dated 2026-05-01. All seeds carry an `originSessionId` UUID, so they are distinguishable from user-generated memories — but they remain static, one-person failure records shipped at plugin install time that never update.

**The problem:**

- They're **static** — they reflect one person's failure modes at a point in time and never update.
- The agentic-loop skill already encodes its own **"Past failure:"** references inline — that's where exemplar failures belong.
- `templates/failure_log.md` is already in `templates/` — the 3 pre-filled rows are the only removable content.

**Proposed action:** Strip the 3 pre-filled rows from `templates/failure_log.md`, keeping the format structure (header, category legend, "append above this comment" footer). Drop the 4 seeded memory files in `starter-memory/`. The format is useful; the ghost data is not.

---

## 3. ADD: `--dry-run` / `--preview` Mode to `push.sh` and `merge.sh`

**Affected:** `scripts/push.sh`, `scripts/merge.sh`

**Why:**

The bash scripts are deterministic plumbing — they stage, commit, push, create PRs, and merge with `set -euo pipefail`. They do real work immediately with no preview path. The markdown commands (`push.md`, `merge.md`) could pass a `--dry-run` flag but the scripts don't support it.

A `--preview` mode that prints:
- What branch, what remote, what target
- What files would be committed (diff --stat)
- What PR title/body would be sent
- What Jira ticket would be resolved

...would cost ~20 lines per script and give users (and Claude, especially in autonomous loops) a safety net before destructive git operations.

**Proposed action:** Add a `--dry-run` flag to both scripts. When set, print the full planned operation and exit 0 without mutating anything. Wire it through from the markdown commands so users can run `/push --dry-run` or `/merge --dry-run`.

---

## 4. ADD: `no-edit-on-main` PreToolUse Hook

> **✅ IMPLEMENTED 2026-06-25** (branch `feat/no-edit-on-main-hook`): `hooks/scripts/no_edit_on_main.sh` blocks `Write`/`Edit`/`MultiEdit` to `.py/.ts/.tsx/.js/.jsx/.go` on `main`/`master` (docs/config pass — the carve-out is the extension filter). Built test-first; `hooks/scripts/tests/no_edit_on_main.test.sh` passes 11/11. Registered in `hooks.json` (`PreToolUse` matcher `Write|Edit|MultiEdit`) and `install.sh`. The phantom `no-edit-on-main.sh` reference in `commands/workflow.md` corrected to the real underscore name and made accurate. No single-line auto-carve (loophole + unreliable across stateless calls); escape is branch-first or a `settings.json` permission.

**Affected:** New hook script `hooks/scripts/no_edit_on_main.sh`, `hooks/hooks.json`

**Why:**

`/workflow`'s "Escape hatches" section (workflow.md:186) references a `no-edit-on-main.sh` hook that does not exist:

> "One-line hotfix / docs-only change: skip `/workflow` entirely. Those don't need a worktree per the `no-edit-on-main.sh` hook's carve-out (only `.py/.ts/.tsx/.js/.jsx/.go` files are blocked on main)."

But **no such hook exists** in `hooks/hooks.json` or `hooks/scripts/`. The worktree discipline is purely advisory — encoded in `/workflow`'s prose. If someone edits a `.py` file on `main` without running `/workflow`, nothing stops them.

This is exactly the kind of thing that belongs in a **PreToolUse hook** per the plugin's own enforcement model: *"Hooks = mechanical enforcement. If it must be enforced even when Claude doesn't cooperate, it's a hook."*

**Proposed action:** Create a `PreToolUse` hook (matching `Write`/`Edit`/`MultiEdit`) that checks `git branch --show-current` against `main`/`master` and blocks edits to code files (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`). Carve out single-line hotfixes and docs-only files. ~40-line bash script.

---

## 5. ADD: Integration Test for Cross-Guard Consistency

**Affected:** `hooks/scripts/tests/` (new test), `hooks/scripts/lib/loop_state_common.sh`

**Why:**

`loop_state_guard.sh` (C1) and `loop_stall_guard.sh` (C2) share `lib/loop_state_common.sh` via `source` — a clean, well-designed extraction specifically to prevent the two guards from drifting on "what is an active loop." The path helper (`lib/agentic_loop_path.sh`) is also shared.

But **no test verifies this drift-prevention works.** The design specs mention the C1 test suite (8/8) but that only tests `loop_state_guard.sh` in isolation. There is no integration test that feeds the same transcript to both guards and asserts they agree on:

- Invocation count (`als_stable_invocations` returns identical values)
- Active/inactive boundary (same gate 3 outcome)
- Path resolution (same `als_resolve_path` output for the same cwd)

This would catch the exact failure mode the shared library was designed to prevent — one guard's detection logic accidentally diverging from the other's.

**Proposed action:** Add an integration test (`hooks/scripts/tests/loop_guard_consistency.test.sh`) that feeds synthetic transcripts to both guards and asserts agreement on all shared detection primitives. This is the test the shared-library extraction deserves.

---

## 6. CHANGE: `check_confidence_labels.sh` Floor Is Too Low

**Affected:** `hooks/scripts/check_confidence_labels.sh`

**Current behavior:**

- Blocks responses **≥ 200 characters** with **zero** confidence labels
- A 199-char response with unchecked claims sails through
- A 200-char response with a single `(inferred)` buried mid-paragraph passes, even if 5 other claims are unlabeled

The discipline instructions acknowledge the gap: *"This is the standard you aim for; the `check_confidence_labels.sh` Stop hook enforces a floor below it."* But the `failure_log.md` itself documents that *"warn-mode + memory-only enforcement is mechanically insufficient"* — and a floor this low is effectively warn-mode with extra steps.

**Proposed action:** Make the check proportional rather than binary:

- **Minimum viable:** Require label count to scale with response length — e.g., `≥ 1 label per 500 characters` rather than a flat "≥1 label and ≥200 chars"
- **Stronger (more complex):** Per-claim checking — if a response has 3+ substantive claims (detectable via sentence structure: assertions about code behavior, architectural claims, "should"/"must" statements), require at least 2 of them to be labeled

The proportional approach is straightforward to implement in bash (integer division on `${#text}`) and closes the gap between the advisory ideal and the enforced floor without requiring NLP-level claim detection.

---

## 7. CHANGE ✅ DONE: `destructive_bash_gate.sh` Supports a Per-Project Allowlist

**Affected:** `hooks/scripts/destructive_bash_gate.sh`

**Current behavior:**

A hardcoded regex permanently blocks: `rm -rf`, `git push --force`, `git push --force-with-lease`, `git reset --hard`, SQL `DROP`/`TRUNCATE`, `dd`, `mkfs`, `chmod -R 777`, `git commit --no-verify`. The only override is adding a Bash permission rule to `settings.json`.

**Problems:**

- **`git push --force-with-lease`** is blocked alongside naked `--force`. Force-with-lease is the safer variant and is commonly used after rebasing a feature branch. Blocking it outright forces users to add a `settings.json` escape hatch, which then opens the door to naked `--force` as well if they add a broad permission.
- **`git commit --no-verify`** is sometimes legitimate in CI pipelines where pre-commit hooks run separately. Blocking it offers no per-project override.
- **No version-controlled, auditable escape.** The only escape is `.claude/settings.json`, which lives outside the repo and isn't version-controlled.

**Shipped action:** Mirrors the pattern established by `test_gate.sh` — reads a `.claude/destructive_allowlist` file (if it exists) that lists specific keywords to permit. Empty or missing file = default behavior (block everything). This keeps the secure default while giving teams an opt-in escape that's version-controlled, auditable, and granular (allow `force-with-lease` without allowing naked `--force`). Shipped 2026-07-07 (`4768a3b`): `allowlist_permits()` in `destructive_bash_gate.sh` (closed keyword vocabulary, fail-closed on missing/empty/garbage), with a passing test suite in `hooks/scripts/tests/destructive_bash_gate.test.sh`. (verified — destructive_bash_gate.sh:83-95)

---

## 8. RETRACTED: `agentic-loop` Delegation — Design Already Exists in Source

**Affected:** `skills/agentic-loop/SKILL.md`, `skills/writing-plans/SKILL.md`, `skills/test-driven-development/SKILL.md`

**Correction:** The original review claimed Phases 2.7/2.8 embed `writing-plans` and Phases 3/3a embed `test-driven-development`. This is false. Source check confirms: Phase 2.8 explicitly invokes `coderails:writing-plans` (SKILL.md:209), and Phases 3/3a invoke `coderails:test-driven-development` (SKILL.md:239,260). These phases already delegate by skill name — the design this proposal argued for is already implemented. (verified — SKILL.md:207-260)

**What is actually inline:** Only Phase 0.5 (orchestrator self-policing — governs main context, has no natural home elsewhere) and Phase 2.6 (clean-migration disposition — writing-plans covers plan writing, not migration policy). Phase 2.7 (spec) is deliberately inline per Spec E — it commits already-resolved design to disk, so a delegated skill is the wrong tool.

**Revised assessment:** The agentic-loop skill is about as delegated as it can get. This proposal is retracted.

---

## Summary Table

| # | Action | Item | Lines Affected |
|---|--------|------|----------------|
| 1 | **Remove** | Wiki subsystem (4 skills, AGENTS.md wiki portions, templates/, `/workflow` Phase 5) | -30% of plugin surface area |
| 2 | **Remove** | Pre-filled `starter-memory/` content + `failure_log.md` rows (keep format) | ~4 memory files + 3 table rows |
| 3 | **Add** | `--dry-run`/`--preview` to `push.sh` and `merge.sh` | ~20 lines per script |
| 4 | **Add ✅ DONE** | `no-edit-on-main` PreToolUse hook | shipped 2026-06-25: `no_edit_on_main.sh` + test (11/11) + hooks.json + install.sh |
| 5 | **Add** | Integration test for C1/C2 guard consistency | ~50-line test script |
| 6 | **Change** | `check_confidence_labels.sh` from binary to proportional | ~5-line logic change |
| 7 | **Change ✅ DONE** | `.claude/destructive_allowlist` for `destructive_bash_gate.sh` | shipped 2026-07-07 (`4768a3b`): `allowlist_permits()` + test suite |
| 8 | **Retracted** | agentic-loop delegation — design already exists in source | No change needed |

---

## Design Invariants Preserved

All proposals respect the codebase's existing design invariants:

- **Enforcement model**: New enforcement (no-edit-on-main) is a hook; advisory changes (dry-run) are command-level. No confusion of the two.
- **Bash 3.2 compatibility**: All proposed bash changes use macOS-compatible syntax (no associative arrays, no `${var,,}`, no `mapfile`).
- **`install.sh` idempotency**: Removals would be handled by `uninstall.sh` reverse logic; additions would follow the existing `chmod +x` / `hooks.json` registration pattern.
- **Single-source truths**: The C1/C2 test reinforces the shared library pattern; delegation changes reinforce the single-skill-owns-instruction pattern.

---

## Post-review findings (verified + shipped 2026-06-25)

Three findings raised after the original review (not in the table above), each source-verified then built/merged:

| Finding | Action | Result |
|---|---|---|
| **A** | Shared `lib/discipline_common.sh` | **✅ PR #29.** Extracted the duplicated transcript text-extraction jq + retry loop from `check_confidence_labels.sh`, `check_verify_loop.sh`, `discipline_catchup.sh` into `hooks/scripts/lib/discipline_common.sh` (mirrors `lib/loop_state_common.sh`). Behavior-preserving (live block/allow spot-check + 5/5 lib test). |
| **B** | Derive `install.sh` chmod from `hooks.json` | **✅ PR #28.** Replaced the hardcoded chmod list with `jq '.hooks[][].hooks[].command'` + a `hooks/scripts/lib/*.sh` glob + the 3 explicit standalone scripts. No more drift when a hook is added. Resolved set verified identical to the prior 15. |
| **C** | Build phantom `enforce-pr-workflow.sh` | **✅ PR #30.** Built `hooks/scripts/enforce_pr_workflow.sh` — PreToolUse(Bash) gate blocking `gh pr create` unless `/coderails:push` ran and `gh pr merge` unless `/pr-review-toolkit:review-pr` ran (robust transcript scan: Skill / `push.sh` Bash forms, verified against real transcripts). NO_CONFIG opt-in, dry-run/help passthrough, transcript-absent inert. TDD 14/14. Resolves the second phantom hook reference at `workflow.md:192`. |

Both phantom-hook references the plugin documented but never built (`no-edit-on-main.sh` → #27, `enforce-pr-workflow.sh` → #30) are now real, tested hooks.

