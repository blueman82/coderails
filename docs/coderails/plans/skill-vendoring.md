# Coderails Skill Vendoring — Inventory & Migration Map

**Date:** 2026-06-25
**Status:** Pre-design discussion. Open decisions at the bottom — nothing approved yet.
**Goal:** Make coderails a self-contained development-workflow plugin with **zero dependency on the superpowers plugin**, by mirroring superpowers' core dev-workflow skills into the coderails namespace.

**End state (confirmed):** once this work lands, **superpowers is uninstalled**. coderails must therefore be the *sole* authority — including the session-start bootstrap that superpowers currently provides (see "Bootstrap injection" below). The `#12` collision concern is void because the two never coexist long-term.

> **Branding rule (from Gary):** every *vendored skill's content* is branded coderails — no mention of "superpowers" anywhere in the shipped SKILL.md or companion files. This planning doc references superpowers only because it is the migration source.

---

## The intent

Not one skill — a **complete, exact mirror** of superpowers' core dev-workflow skills, vendored into coderails. The vendored skills become shared building blocks consumed by **both**:

- **The human**, invoking them individually outside any loop (e.g. run `coderails:subagent-driven-development` to execute a plan with per-task subagents, no autonomy envelope).
- **`agentic-loop`**, the autonomous conductor, which calls them end-to-end as the full autonomous flow.

### Architecture model (chosen)

- The new skills are **standalone** — conceptually independent of `agentic-loop`, exactly as they are standalone in superpowers.
- `agentic-loop` is then **rewired to reference them** wherever it currently embeds "how to dispatch a subagent" mechanics inline — the same one-line-reference idiom Phase 3/3a already use for `coderails:test-driven-development` (`SKILL.md:239,260`, verified). This keeps `agentic-loop` slim (likely slims it further), while it retains its **autonomy-only** content (orchestrator-never-implements, verify-artifacts-not-pings, envelope-scoped confirmation cadence).
- **Constraint:** the six C1/C2 no-touch regions in `agentic-loop/SKILL.md` stay byte-identical (the rule that governed Specs C1–E).

---

## 1. What coderails already has (11 skills)

| coderails skill | Origin | superpowers counterpart |
|---|---|---|
| `writing-plans` | **vendored** ✓ | `writing-plans` |
| `test-driven-development` | **vendored** ✓ | `test-driven-development` |
| `agentic-loop` | coderails-original | — (no equivalent; the autonomous conductor) |
| `planning-sequence` | coderails-original | — (Pre-Parade / Premortem / Red Team) |
| `premortem` | coderails-original | — |
| `handoff` | coderails-original | — |
| `improve-prompt` | coderails-original | — |
| `wiki-init` / `wiki-ingest` / `wiki-lint` / `wiki-query` | coderails-original | — |

## 2. What superpowers ships (14 skills)

Two are already vendored (`writing-plans`, `test-driven-development`). The other **12 are absent from coderails.**

## 3. The gap — 12 move candidates

### Clean to vendor (9) — no coderails equivalent, all part of the dev wheel

| # | → coderails skill | Companion files | Note |
|---|---|---|---|
| 1 | `brainstorming` | `scripts/`, `spec-document-reviewer-prompt.md`, `visual-companion.md` | Heaviest. Visual companion runs a browser server. Also references an `elements-of-style:writing-clearly-and-concisely` skill that coderails does **not** have — needs a rebrand decision. |
| 2 | `subagent-driven-development` | `implementer-prompt.md`, `task-reviewer-prompt.md`, `scripts/` | The skill that started this. References #3, #4, #6 by namespace. |
| 3 | `using-git-worktrees` | — | SDD dependency |
| 4 | `requesting-code-review` | `code-reviewer.md` | SDD dependency |
| 5 | `receiving-code-review` | — | Review-loop companion |
| 6 | `finishing-a-development-branch` | — | SDD dependency |
| 7 | `executing-plans` | — | Parallel-session sibling of SDD |
| 8 | `dispatching-parallel-agents` | — | Fan-out helper |
| 9 | `systematic-debugging` | ~10 files (root-cause-tracing, defense-in-depth, condition-based-waiting, test fixtures, `CREATION-LOG.md`) | Some extras are superpowers-internal cruft (`CREATION-LOG.md`, `test-pressure-*.md`), not shippable content — needs a keep/drop pass. |

### Flagged — coderails already covers these another way (all 3 RESOLVED → mirror)

| # | superpowers skill | coderails already has | Decision |
|---|---|---|---|
| 10 | `verification-before-completion` | discipline hooks (`check_confidence_labels`, `check_verify_loop`) + `/verify` `/notchecked` `/assumptions` `/disconfirm` | **MIRROR.** Hooks *enforce* and commands *probe*, but neither is an agent-invokable *method* a subagent can follow mid-task. The skill fills a real altitude gap (same logic as TDD-skill vs test-gate-hook). |
| 11 | `writing-skills` | the `skill-creator` plugin (separate install) | **MIRROR.** Zero-external-dependency is the goal; leaning on a separate plugin reintroduces the dependency being removed. |
| 12 | `using-superpowers` (bootstrap) | nothing direct | **MIRROR → `using-coderails`, + its SessionStart injection hook.** Once superpowers is uninstalled there is no collision, and coderails *needs* the bootstrap or no session-start authority loads at all. See "Bootstrap injection". |

**Resolved set: all 12 → vendored. 11 skills + the bootstrap (`using-coderails` skill + SessionStart hook).**

---

## Dependency graph (drives build order)

```
brainstorming ──► writing-plans(✓) ──► subagent-driven-development ──► finishing-a-development-branch
                                            │
                                            ├─► using-git-worktrees
                                            ├─► requesting-code-review ──► receiving-code-review
                                            └─► test-driven-development(✓)

executing-plans ──► (same dependencies as SDD)
dispatching-parallel-agents ── standalone
systematic-debugging ── standalone
```

**Build leaves first:** `using-git-worktrees`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch` → then `subagent-driven-development` / `executing-plans` → `brainstorming` last (it's the entry point but depends on writing-plans, already present). Standalones (`dispatching-parallel-agents`, `systematic-debugging`) anytime.

---

## Rebranding checklist (applies to every vendored skill)

1. **Namespace rewrite** — every `superpowers:<skill>` cross-reference → `coderails:<skill>`. Miss one and the superpowers dependency survives invisibly.
2. **Body scrub** — no literal "superpowers" string in any shipped file (SKILL.md, prompt templates, companion .md).
3. **Foreign-skill references** — `elements-of-style:*` and any other non-superpowers, non-coderails skill referenced inside a vendored body → rebrand, inline, or drop.
4. **Cruft drop** — superpowers-internal files (`CREATION-LOG.md`, `test-pressure-*.md`, skill-authoring test fixtures) are not shipped.
5. **Plugin registration** — each new skill listed wherever coderails enumerates skills (plugin manifest / install.sh as applicable).
6. **`using-superpowers` → `using-coderails`** only if decision #12 says yes; otherwise the global bootstrap stays the single authority.

---

## Bootstrap injection (load-bearing infra)

The `using-superpowers` bootstrap is not auto-loaded because it is a skill — it loads because superpowers ships a **`SessionStart` hook**. Verified mechanism (`hooks/hooks.json` + `hooks/session-start`, v6.0.3):

- `hooks.json` registers `SessionStart` with matcher `startup|clear|compact`, calling a command hook.
- The script reads `skills/using-superpowers/SKILL.md`, JSON-escapes it via pure bash parameter substitution (`${s//old/new}` — **bash-3.2/macOS-safe**), wraps it as `<EXTREMELY_IMPORTANT>You have superpowers…</EXTREMELY_IMPORTANT>`, and emits `hookSpecificOutput.additionalContext`.

**coderails must replicate this** to survive the superpowers uninstall:

1. Add a `SessionStart` block (matcher `startup|clear|compact`) to coderails' existing `hooks/hooks.json` (which currently has only `UserPromptSubmit` / `Stop` / `PreToolUse`).
2. New script `hooks/scripts/inject_bootstrap.sh` — reads `skills/using-coderails/SKILL.md`, escapes (bash-3.2-safe), wraps in a **coderails-branded** EXTREMELY_IMPORTANT block (no "superpowers" string), emits `additionalContext`.
3. Register the new script in `install.sh`'s chmod enumeration (it lists hook scripts explicitly — verified `install.sh:322–329`).
4. **Transient overlap:** while both plugins are installed during the build, two bootstraps fire (duplicate EXTREMELY_IMPORTANT blocks). Harmless; resolves on uninstall.

---

## Open decisions (for discussion)

1. ~~The 3 flagged overlaps~~ — **RESOLVED: all 12 mirrored** (incl. `using-coderails` + bootstrap hook).
2. **Structure** — recommended **two phases**: Phase 1 vendor the 12 skills + bootstrap hook (mechanical, low-risk); Phase 2 rewire `agentic-loop` to reference them (higher-risk surgery on the slimmed, byte-frozen skill). Confirm vs one-big-spec or per-skill specs.
3. **`brainstorming` visual companion** — **RESOLVED: exact mirror, with a coderails creative twist.** Vendor the full companion (Node server, `visual-companion.md`, just-in-time browser-offer logic) rebranded coderails — and give it its own coderails visual identity/personality rather than a literal copy. Design the twist in the spec.
4. **`agentic-loop` rewiring scope** — Phase 2 of this initiative (per decision 2).
5. **Parked `#4 no-edit-on-main` hook** — on branch `feat/no-edit-on-main-hook`, uncommitted. Resume independently after this initiative.

---

## Provenance

- superpowers source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/` (v6.0.3, verified by directory listing 2026-06-25).
- The "don't vendor SDD" reversal context: Spec D (the construction-seam design, since removed along with the `docs/superpowers` tree in PR #44) declined SDD because `agentic-loop` "already embodies it." This initiative supersedes that call by separating the *standalone human-present* use case (the new skill) from the *autonomous* use case (agentic-loop), and by making coderails fully self-contained.
