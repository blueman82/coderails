# Spec D — Construction-discipline seam (vendored TDD)

**Status:** design, awaiting review
**Branch:** `spec/d-construction-seam`
**Date:** 2026-06-24
**Part of:** the agentic-loop upgrade sequence A → C1 → C2 → B → **D** (A/C1/C2/B merged as PRs #12/#13/#14/#15). D is last.

## Problem

The agentic-loop skill has *verification* discipline (artifact checks, confidence labels, premise-disproving, the C1/C2 stop guards) but no *construction* discipline. Phase 3/3a tells a worker it "implements **and** verifies its own artifact" — but never says **how to build**. Neither `coderails:agentic-loop` nor `superpowers:subagent-driven-development` fills this: both say "implement" and stop. The genuine gap is red-green-refactor — write the failing test first, watch it fail, then minimal code to pass.

## Decision (and why it changed from Spec A's note)

Spec A's roadmap recorded D as a *reference* to `superpowers:test-driven-development` ("reference, not vendor"). That assumed the user has the superpowers plugin installed. During D's brainstorming this was overturned: **vendor the discipline as coderails' own skill** so coderails has zero cross-plugin dependency and stays a true self-contained zip. The reference now points at a coderails-owned skill that always ships with the plugin.

**What is vendored:** `coderails:test-driven-development` plus a `testing-anti-patterns.md` companion (adapted from superpowers' red-green-refactor skill into coderails' voice and namespace).

**What is NOT vendored:** `subagent-driven-development`. `coderails:agentic-loop` already embodies the orchestrator's dispatch-per-task + review pattern (Phase 3/3a/4b); a separate coderails SDD skill would duplicate the skill Spec B just slimmed. SDD remains superpowers' general-purpose build-time tool. **agentic-loop is the orchestration authority; D adds only the worker's construction method, which is the real gap.**

## Reachability (verified during planning-sequence)

The seam can actually *fire*, not just exist — confirmed against the skill's own text:
- **Workers have skill access.** Phase 2 already instructs a spawned agent "to invoke each relevant skill via its `Skill` tool call" (SKILL.md line 138). Spawning an agent and naming a skill in its prompt is an established, working pattern in this skill.
- **The namespaced idiom is established.** Phase -1 references a coderails skill as `/coderails:improve-prompt`; `coderails:test-driven-development` follows that exact idiom, and the `coderails:` prefix disambiguates it from `superpowers:test-driven-development` when both plugins are installed.

This closes the one reachability question the planning-sequence flagged as load-bearing. The honest boundary (same as the C1/C2 hooks): D guarantees the worker is *told* to construct via TDD and *can* reach the skill — not that it mechanically did. D is the **advisory construction layer**; mechanical enforcement is a hook, explicitly deferred (see Out of scope).

## Constraints

- **Code-guarded reference, with a concrete self-exemption-resistant test.** TDD presupposes code-with-tests; the agentic-loop drives non-code work too (Spec B itself was a prose edit, grep-verified, no TDD). The guard fires "when the deliverable is code" — but a vague guard invites self-exemption (a worker calling a code change "mostly config"), the failure mode Phase 2.6 fixes with a concrete test ("what named thing does this remove?"). So phrase the guard concretely: **"if the change adds or alters a function, method, or branch that *can* carry a test, TDD applies — even if the PR also touches non-code files."** Pure docs/config/prose with no testable code keeps the "verify your artifact by inspection" contract.
- **Sonnet-only untouched.** TDD is *how* to build, not *which model*. The Phase 3/3a `model: sonnet` rule is not weakened. The new skill must not (re)introduce any model-selection guidance that could escalate workers off sonnet.
- **No cross-plugin dependency.** The vendored skill is coderails-owned; the Phase 3/3a reference uses the `coderails:` namespace.
- **C1/C2 no-touch regions stay byte-stable.** Phase 3 and Phase 3a are NOT among the six no-touch regions, so editing them is allowed — but D must not touch the frontmatter `description:`, Phase -2, the Phase 0.5 LOOP-STOP bullet, the Phase 13 KPI bullet, the Stop-conditions "Declaring the stop" block, or the `## Context-window persistence` section.
- **Don't regress B's slim.** The Phase 3/3a additions are surgical one-liners, not a re-expansion.

## Deliverable 1 — `skills/test-driven-development/SKILL.md` (+ companion)

A new coderails skill, built with skill-creator, adapting the superpowers red-green-refactor discipline. Self-contained (SKILL.md + one reference doc), no superpowers content vendored verbatim where coderails has its own voice. **Adapt to a focused skill, not a 371-line copy** — re-importing the full superpowers file would re-introduce the bulk Spec B just cut, and an over-long skill is a worse trigger. Keep: the Iron Law, the cycle, the code-guard, a compact rationalizations set, the anti-patterns companion. Drop superpowers-specific framing and any padding.

**Frontmatter:**
- `name: test-driven-development` (invoked as `coderails:test-driven-development`; namespace prevents collision with `superpowers:test-driven-development`).
- `description:` single-quoted (per commit `e6e39dd`, strict-YAML safe). It must trigger when a worker is about to implement **code** (a feature, bugfix, refactor with tests) — and carry the code-guard so it does not fire on docs/config/prose. Example shape: `'Use when implementing or fixing CODE that can carry tests — write the failing test first, watch it fail, then minimal code to pass (red-green-refactor). Does NOT apply to docs/config/prose edits, which verify by inspection instead.'`

**Body (adapted, coderails voice):**
- The Iron Law: no production code without a failing test first.
- Red → verify-red (watch it fail for the right reason) → green (minimal code) → verify-green (pristine output) → refactor (stay green).
- Good-vs-bad test examples (one behaviour, clear name, real code not mock-tautology).
- The rationalizations table + red-flags list (the "delete and restart" discipline).
- A short "When NOT to use" that states the code-guard explicitly: prose, config, generated code, throwaway spikes — defer to the human / verify by inspection.
- Links to the companion `testing-anti-patterns.md`.

**`skills/test-driven-development/testing-anti-patterns.md`:** adapted companion — testing mock behaviour instead of real behaviour, adding test-only methods to production classes, mocking without understanding dependencies.

**Registration:** none required. Claude Code auto-discovers `skills/*/SKILL.md`; plugin.json does not enumerate skills and install.sh does not touch them (verified). Optional polish: add `tdd`/`test-driven-development` to plugin.json `keywords` and mention the skill in the plugin/marketplace `description` — cosmetic, not load-bearing.

## Deliverable 2 — wire the seam into `agentic-loop` Phase 3/3a

Two surgical additions, both code-guarded, both naming `coderails:test-driven-development`:

1. **Phase 3 task-description checklist (~line 209):** add a bullet to the "Each task description must include" list — e.g. `Construction method — when the deliverable is code, instruct the worker to build it via \`coderails:test-driven-development\` (failing test first → minimal code → refactor). For non-code deliverables (docs, config), keep the verify-your-artifact contract; there is no test to write first.`
2. **Phase 3a single-agent prompt contract (~line 233):** add a matching bullet to the prompt-contract list — same code-guarded instruction, phrased for the single impl+verify agent, reinforcing that its existing "verify step" becomes "watch the test fail, then watch it pass" when the work is code.

Both reuse the existing one-line-reference idiom (the way Phase -1 references improve-prompt). Neither weakens the `model: sonnet` rule sitting beside them.

**Placement matters — don't bury it.** The agentic-loop's own Phase 9 lesson is that scope-shaping instructions get shortcut when they sit low in a prompt ("scope-suppression instructions go above scope-additive instructions"). A construction-method instruction is scope-shaping. So in Phase 3a's prompt contract, the TDD line goes **near the top of the contract list**, not buried among the trailing bullets — it shapes *how* the worker builds, which must register before the worker starts. This is the one mitigation that keeps an advisory seam from being ignored under load.

## Verification

1. **New skill loads.** `skills/test-driven-development/SKILL.md` exists with valid single-quoted frontmatter; the companion doc exists and is linked. Confirm the skill's `description` contains the code-guard (a "not for docs/config/prose" clause).
2. **Seam present, code-guarded, and placed high.** Grep Phase 3 and Phase 3a for `coderails:test-driven-development` — each reference is accompanied by the concrete code-guard ("function, method, or branch that can carry a test"), not a vague "when it's code" or unconditional "always TDD". In Phase 3a, confirm the TDD line sits near the TOP of the prompt-contract bullet list (per the Phase 9 placement lesson), not among the trailing bullets.
3. **Sonnet-only intact.** The Phase 3/3a `model: sonnet` rules are unchanged; the new skill body contains no model-selection guidance that could escalate a worker off sonnet (grep the new skill for `opus`/`model:`/`most capable` → none, or only in a "this is orthogonal to TDD" note).
4. **C1/C2 no-touch regions untouched.** `git diff origin/main -- skills/agentic-loop/SKILL.md` — every hunk falls in Phase 3 or Phase 3a; no hunk intersects the six no-touch regions (same region anchors as Spec B). Frontmatter `description:` byte-identical.
5. **No dependency leak.** Grep the whole branch diff for `superpowers:` in the shipped skill text — the agentic-loop reference points at `coderails:test-driven-development`, not `superpowers:`.
6. **Hooks still green.** The three hook suites (path 3/3, state-guard 8/8, stall-guard 8/8) pass — D is markdown-only, so they should be unaffected.

## Out of scope

- No `subagent-driven-development` skill (agentic-loop already embodies it).
- No enforcement hook for TDD — a skill reference is advisory by design; if TDD must be *mechanically* enforced in the loop, that is a PreToolUse hook (Spec C territory), out of scope here.
- No changes to hooks, `hooks.json`, `install.sh`, or `lib/` scripts.
- The deferred `tsh ssh` Phase 4/12 cleanup from Spec B — could be batched here as a trivial extra, decided at plan time, but is not core to D.
