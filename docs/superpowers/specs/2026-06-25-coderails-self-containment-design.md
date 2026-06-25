# Coderails Self-Containment — Design Spec

**Date:** 2026-06-25
**Status:** Design approved (full-autonomous envelope). Pre-flight review (planning-sequence) pending.
**Supersedes:** the SDD out-of-scope decision in `2026-06-24-d-construction-seam-design.md` (lines 18, 78) — see "Relationship to Spec D".
**Working inventory:** `docs/coderails-skill-vendoring-plan.md` (the discussion artifact this spec formalises).

---

## Motivation

coderails already vendored `writing-plans` and `test-driven-development` (Specs D, E) to become a "true self-contained zip" with zero cross-plugin dependency. But the rest of the development workflow — brainstorming, subagent-driven execution, code review, worktrees, debugging — still lives only in the **superpowers** plugin. coderails depends on superpowers for everything except planning and TDD.

This spec closes that gap: vendor superpowers' **entire core development-workflow skill set** into the coderails namespace, rebranded, so coderails depends on superpowers for **nothing**. The end state is that the user can **uninstall superpowers** and lose no capability.

## Objective & end state

- Mirror the 12 superpowers skills not already in coderails into `coderails:*`, fully rebranded (no literal "superpowers" string in any shipped file).
- Add the **SessionStart bootstrap** that superpowers currently provides, so `coderails:using-coderails` auto-loads each session once superpowers is gone.
- Rewire `coderails:agentic-loop` to **reference** the vendored skills instead of embedding subagent-dispatch prose inline.
- **End state:** superpowers uninstalled; coderails is the sole development-workflow authority.

## Architecture

Two consumers share the vendored skills as building blocks:

1. **The human**, invoking a skill directly outside any loop (e.g. run `coderails:subagent-driven-development` to execute a plan with per-task subagents, no autonomy envelope).
2. **`coderails:agentic-loop`**, the autonomous conductor, which calls them end-to-end as the full autonomous flow.

The vendored skills are **standalone** — conceptually independent of `agentic-loop`, exactly as they are standalone in superpowers. `agentic-loop` is a *consumer*, not a parent. This is the resolution of the Spec D "duplication" objection: the new skills are the human-present building blocks; `agentic-loop` keeps only its **autonomy-specific envelope** (orchestrator-never-implements, verify-artifacts-not-pings, envelope-scoped confirmation cadence, the C1/C2 guard integration) and *delegates* the generic dispatch mechanics by reference.

## Relationship to Spec D

Spec D (`2026-06-24-d-construction-seam-design.md`, lines 18, 78) declined to vendor `subagent-driven-development`, reasoning "agentic-loop already embodies it." That call conflated two altitudes:

- **Autonomous multi-PR orchestration** → `agentic-loop` (correct, embodied).
- **Same-session, human-present plan execution** → no coderails skill existed; the only option was `superpowers:subagent-driven-development`, which kept a cross-plugin dependency alive — contradicting Spec D's own zero-dependency goal (line 14).

This spec supersedes that narrow call by separating the two altitudes and making coderails fully self-contained. `agentic-loop` is not duplicated — it is slimmed to reference the standalone skill.

## Scope — 12 skills + bootstrap

Vendored as `coderails:*`, rebranded. Companion files carried unless noted.

**Tier A — leaves (no in-graph dependencies):**
1. `using-git-worktrees`
2. `requesting-code-review` (+ `code-reviewer.md`)
3. `receiving-code-review`
4. `finishing-a-development-branch`

**Tier B — executors (depend on Tier A + already-vendored writing-plans/TDD):**
5. `subagent-driven-development` (+ `implementer-prompt.md`, `task-reviewer-prompt.md`, `scripts/`)
6. `executing-plans`

**Tier C — entry / standalone:**
7. `brainstorming` (+ `spec-document-reviewer-prompt.md`, `scripts/`, **visual companion** — see below)
8. `dispatching-parallel-agents`
9. `systematic-debugging` (companion `.md` references kept; superpowers-internal cruft dropped — see Rebranding)

**Tier D — overlaps coderails already covers another way, vendored anyway for completeness:**
10. `verification-before-completion` — coderails enforces verification via discipline hooks + `/verify` `/notchecked` `/assumptions` `/disconfirm`, but none is an agent-invokable *method*; the skill fills that altitude gap.
11. `writing-skills` — `skill-creator` plugin covers this, but leaning on it reintroduces an external dependency; vendor for self-containment.

**Tier E — bootstrap:**
12. `using-coderails` (mirror of `using-superpowers`) **+ the SessionStart injection hook** (see "Bootstrap injection").

Already present (no action): `coderails:writing-plans`, `coderails:test-driven-development`.

## Bootstrap injection (load-bearing infra)

The bootstrap is not auto-loaded because it is a skill — it loads because superpowers ships a **SessionStart hook**. Verified mechanism (`superpowers/6.0.3/hooks/hooks.json` + `hooks/session-start`):

- `hooks.json` registers `SessionStart` with matcher `startup|clear|compact`.
- The script reads `skills/using-superpowers/SKILL.md`, JSON-escapes it via pure bash parameter substitution (`${s//old/new}` — **bash-3.2 / macOS-safe**), wraps it as `<EXTREMELY_IMPORTANT>…</EXTREMELY_IMPORTANT>`, and emits `hookSpecificOutput.additionalContext`.

coderails must replicate this or `using-coderails` never auto-fires once superpowers is uninstalled:

1. Add a `SessionStart` block (matcher `startup|clear|compact`) to coderails' existing `hooks/hooks.json` (currently only `UserPromptSubmit` / `Stop` / `PreToolUse`).
2. New script `hooks/scripts/inject_bootstrap.sh` — reads `skills/using-coderails/SKILL.md`, escapes (bash-3.2-safe), wraps in a **coderails-branded** EXTREMELY_IMPORTANT block (no "superpowers" string), emits `additionalContext` in Claude Code's nested shape.
3. Register the new script in `install.sh`'s chmod enumeration (it lists hook scripts explicitly — verified `install.sh:322–329`) and `uninstall.sh` symmetry.
4. **Testing:** `inject_bootstrap.sh` is executable logic → ships a `hooks/scripts/tests/inject_bootstrap.test.sh` (TDD), asserting it emits valid JSON with the skill content embedded and the coderails branding, and that it no-ops gracefully if the skill file is missing.
5. **Transient overlap:** while both plugins are installed during the build, two bootstraps fire (duplicate EXTREMELY_IMPORTANT blocks). Harmless; resolves on uninstall.

## Visual companion — exact mirror with a coderails twist

Mirror superpowers' browser-based visual companion in full (the Node server, `visual-companion.md`, the just-in-time browser-offer logic, per-question browser-vs-terminal decision). The **creative twist** (coderails identity, not a literal copy):

- **Theme:** a "blueprint / rail" aesthetic — coderails palette, rail-line connectors for diagrams, a drafting-table canvas. Branded coderails throughout.
- **Original feature (the twist):** a persistent **Decision Ledger** panel that records each design decision as it is made during brainstorming (the question, the chosen option, the rationale). This aligns the companion with coderails' discipline/verification ethos — the same "record the decision" instinct as `progress.json` and the confidence-label hooks — and produces a by-product the spec-writer can fold straight into the design doc.
- Behaviour is otherwise identical to the source; only identity and the ledger feature differ.

## Rebranding rules (every vendored file)

1. **Namespace rewrite** — every `superpowers:<skill>` cross-reference → `coderails:<skill>`. Miss one and the dependency survives invisibly. Vendored bodies reference siblings: e.g. `subagent-driven-development` names `using-git-worktrees`, `requesting-code-review`, `finishing-a-development-branch`, `test-driven-development`, `writing-plans`.
2. **Body scrub** — no literal "superpowers" string in any shipped file (SKILL.md, prompt templates, companion `.md`, scripts).
3. **Foreign-skill references** — non-superpowers, non-coderails refs inside a vendored body (`elements-of-style:writing-clearly-and-concisely` in `brainstorming`) → rebrand, inline the guidance, or drop. Decision per occurrence at build time; default: drop the optional reference, keep the behaviour.
4. **Cruft drop** — superpowers-internal files not shipped: `CREATION-LOG.md`, `test-pressure-*.md`, and skill-authoring test fixtures under `writing-skills/` that are about superpowers' own development, not the skill's function. Keep content companions (`root-cause-tracing.md`, `defense-in-depth.md`, `condition-based-waiting.md`, `testing-anti-patterns.md`-style).
5. **Plugin registration** — each new skill discoverable wherever coderails enumerates skills; new hook script chmod'd by `install.sh` and reversed by `uninstall.sh`.
6. **Description fidelity** — each skill's frontmatter `description` (the trigger surface) is preserved in meaning so triggering behaviour matches superpowers; only the namespace and brand change.
7. **Non-markdown rebrand targets (brainstorming visual companion)** — these need code-level edits, not just namespace swaps (the scrub `grep -ri superpowers` *will* flag them, so they block the Phase 1 gate):
   - `brainstorming/scripts/server.cjs`: rename `SUPERPOWERS_VERSION` → `CODERAILS_VERSION`; `SUPERPOWERS_BRAND_IMAGE_URL` → coderails brand or removed; brand text strings → `coderails`.
   - `brainstorming/scripts/start-server.sh`: rewrite the session/port/token paths `.superpowers/brainstorm/` → `.coderails/brainstorm/` (verified lines 117/120/121) and the `--project-dir` comment.
   - `brainstorming/scripts/frame-template.html`: `<title>` → coderails.
   - `brainstorming/visual-companion.md`: `.superpowers/brainstorm/` path refs → `.coderails/brainstorm/`.
   - Renaming the session dir is a deliberate behavioural change (state writes to a new path; old superpowers sessions won't be visible to coderails). Acceptable per the transient-overlap precedent; resolves on uninstall. The external brand-image URL is removed (no coderails-hosted replacement) rather than left pointing at a superpowers asset.
8. **`references/` mirroring** — `using-superpowers/references/` is vendored as `using-coderails/references/`, and the relative refs into it are updated: `executing-plans/SKILL.md:14` and `writing-skills/SKILL.md:12` both point at `../using-superpowers/references/` (verified) → `../using-coderails/references/`.
9. **Semantic (not mechanical) rewrites** — two passages break under a pure namespace swap and need rewriting:
   - `executing-plans/SKILL.md:14` recommends "Superpowers works better with subagents… use `superpowers:subagent-driven-development`." Inside a coderails-only install this becomes "use `coderails:subagent-driven-development` instead of this skill" — self-referential. Rewrite to the altitude distinction (executing-plans = parallel session; SDD = same session), no brand recommender.
   - `writing-skills/testing-skills-with-subagents.md` contains `superpowers:test-driven-development` in an *illustrative* (non-functional) example. **Keep the file** (it teaches testing any skill — useful to coderails authors); rebrand the illustrative refs to `coderails:` so the scrub passes, accepting they are examples, not live calls.

## Phasing

**Phase 1 — Vendor (mechanical, low-risk).** All 12 skills + the bootstrap hook. Mostly copy + rebrand + register; the only executable logic is `inject_bootstrap.sh` (TDD) and the visual-companion server (verified by running it). Skills verified by inspection (markdown) + a rebrand-scrub check (no "superpowers" string survives). This phase does **not** touch `agentic-loop`, so it cannot regress the autonomous loop.

**Phase 2 — Rewire (additive, lower-risk than first framed).** Pre-flight correction (verified): agentic-loop's Phase 3/3a is **entirely autonomy-specific** (manifest discipline, pre-push scope assertion, terminal-state contract, TeamCreate-vs-solo ladder, disposition pass-through) — there is **no generic dispatch prose to remove**, and the TDD construction reference is already a one-liner. So the rewire is an **addition, not a clean-break replacement**:
- Add a single reference line to Phase 3/3a's worker-construction instruction pointing to `coderails:subagent-driven-development` for the worker-prompt construction contract (the standalone-skill home of implementer/reviewer prompt templates) — the same one-line idiom Phase 3/3a already use for `coderails:test-driven-development`.
- **Disposition: N/A** — no existing path is retired; this is additive capability. (This supersedes the earlier "clean-break" framing, which assumed removable prose that does not exist.) Recorded at Phase 2.6.
- **Stale-ref cleanup (same file, same PR):** fix the dead `claude-guardrails` namespace — `agentic-loop/SKILL.md:13` and `:134` reference `/claude-guardrails:assumptions` / `:notchecked` → `coderails:assumptions` / `coderails:notchecked` (verified: both commands exist in `commands/`). These lines are **not** in any C1/C2 no-touch region (verified against Spec B's six-region list).
- The six **C1/C2 no-touch regions stay byte-identical** (the rule that governed Specs C1–E; region byte-diff is the primary gate). For reference, the six regions are: the frontmatter `description`, Phase -2, the Phase 0.5 LOOP-STOP bullet, the Phase 13 KPI bullet, the Stop-conditions LOOP-STOP block, and the Context-window-persistence lifecycle section.
- Report the slim-delta (expected: a small net *addition*, not a removal) and confirm the three hook suites still pass (path 3/3, state-guard 8/8, stall-guard 8/8).

## Dependency graph (drives build order)

```
brainstorming ─► writing-plans(✓) ─► subagent-driven-development ─► finishing-a-development-branch
                                          ├─► using-git-worktrees
                                          ├─► requesting-code-review ─► receiving-code-review
                                          └─► test-driven-development(✓)
executing-plans ─► using-git-worktrees, finishing-a-development-branch, writing-plans(✓)   [NO requesting-code-review dep — verified executing-plans/SKILL.md:36,68-70]
systematic-debugging ─► test-driven-development(✓), verification-before-completion   [verified systematic-debugging/SKILL.md:179,287-288]
dispatching-parallel-agents · verification-before-completion · writing-skills · using-coderails+hook  (standalone, 0 cross-refs)
```

Build leaves first (Tier A), then executors (Tier B), then standalones/entry/overlaps/bootstrap (Tiers C–E), then Phase 2 rewire last (depends on the vendored skills existing). Highest rebrand-error risk (most cross-refs): `subagent-driven-development` (9 `superpowers:` occurrences), then `executing-plans` and `writing-skills` (~5 each) — verified by grep.

## Testing & verification strategy

- **Skills (markdown):** verified by inspection + automated **rebrand scrub** (`grep -ri 'superpowers' <skill dir>` returns nothing in shipped files) + frontmatter validity.
- **`inject_bootstrap.sh`:** TDD with `inject_bootstrap.test.sh` (valid JSON, content embedded, coderails branding, missing-file no-op).
- **Visual companion server:** verified by launching it and confirming it serves (mirrors how superpowers verifies its own).
- **agentic-loop rewire (Phase 2):** C1/C2 byte-diff gate + the three existing hook suites (path 3/3, state-guard 8/8, stall-guard 8/8) green.
- **Per-PR:** `/pr-review-toolkit:review-pr all` (6 agents) + `/security-review`.

## Success criteria (loop "done")

1. All 12 skills present as `coderails:*`, rebrand-scrub clean, frontmatter valid.
2. `using-coderails` auto-loads via the new SessionStart hook (demonstrated).
3. `inject_bootstrap.test.sh` green; existing hook suites green.
4. `agentic-loop` rewired, C1/C2 regions byte-identical, slim-delta reported.
5. `install.sh`/`uninstall.sh` updated and idempotent.
6. With superpowers *disabled*, a representative flow (brainstorm → writing-plans → SDD) runs on coderails skills alone.

## Out of scope

- Uninstalling superpowers (the user does this post-merge; this spec only makes it *possible*).
- The parked `#4 no-edit-on-main` hook (separate task).
- Changing coderails' existing original skills (`planning-sequence`, `premortem`, `handoff`, `improve-prompt`, wiki-*) — untouched.
- Re-vendoring `writing-plans` / `test-driven-development` (already present).
- **`pr-review-toolkit` dependency (retained, intentional).** `coderails:agentic-loop` Phase 4b (`SKILL.md:287-304`) references six `pr-review-toolkit:*` agents by name. This spec removes the **superpowers** dependency only — it does **not** make coderails free of *all* external plugins. "Self-contained" here means "no superpowers needed," not "no plugins needed." A user uninstalling superpowers must keep `pr-review-toolkit` installed or the Phase 4b review gate fails. Scope the success claim accordingly: the deliverable is *zero superpowers dependency*, verified by the rebrand scrub, not *zero plugin dependency*.

## Provenance

- superpowers source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/` (v6.0.3, verified by directory listing 2026-06-25).
- Bootstrap mechanism: `superpowers/6.0.3/hooks/{hooks.json,session-start}` (verified by read).
- Auto-commit environment hook: `~/.claude/hooks/auto_commit.py` (PostToolUse Write/Edit/MultiEdit, per-file, current branch, `auto_push:false` — verified by read; relevant to base hygiene during execution).
