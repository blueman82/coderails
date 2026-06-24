# Spec B — Slim the agentic-loop skill

**Status:** design, awaiting review
**Branch:** `spec/b-slim-skill`
**Date:** 2026-06-24
**Part of:** the agentic-loop upgrade sequence A → C1 → C2 → **B** → D (A/C1/C2 merged as PRs #12/#13/#14).

## Problem

`skills/agentic-loop/SKILL.md` has grown to 454 lines after Specs A, C1, and C2 layered new
discipline onto it. Two distinct kinds of bulk now make the skill harder to read and maintain
without adding discipline:

1. **Vestigial corporate-stack content.** Phases 7 (skip-validation) and 8 (rebase-before-push)
   describe a specific deploy stack — docker-compose, Teleport (`tsh ssh`), a `./deploy` script with
   `--force --skip-drain --skip-validation`, black/isort. This is residue from a non-generic
   corporate fork of the plugin. It does not apply to the generic shipped skill, and the
   `feedback_deploy_skip_drain_default` memory Phase 7 cites does not exist in any local memory dir
   (it lived on the corporate machine). A shippable, stack-agnostic skill should not carry it.

2. **Long "Past failure:" war stories.** Sixteen multi-sentence narratives (see inventory below)
   each wrap a one-line lesson in several sentences of retelling. The lesson is load-bearing; the
   narrative length is not.

## Goal

Cut length without losing discipline, and **without touching any of the C1/C2 contract text the
Stop hooks depend on.**

## Non-negotiable constraint — preserve verbatim

The following regions teach the model the exact behaviour the Stop hooks check for in the
transcript. Editing them risks the model no longer emitting the declaration / writing the stub the
hooks require, which turns the hooks from a safety net into a stall generator. These regions are
**no-touch**; slimming routes around them:

1. **Frontmatter `description:`** — untouched, stays single-quoted (commit `e6e39dd` made it
   single-quoted so strict YAML parsers accept it; unquoting would break skill loading).
2. **Phase -2 (stub-first)** — the path-helper instruction, the JSON stub block, and the
   carry-forward rule for `completed_marker`.
3. **Phase 0.5 LOOP-STOP bullet** — the `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>`
   bullet and its `complete`⇒teardown sentence.
4. **Phase 13 `loop_stop_counts` KPI bullet** — the "LOOP-STOP declarations by category" bullet.
5. **Stop-conditions LOOP-STOP contract block** — the four-category list and "Declaring the stop"
   subsection.
6. **Context-window persistence lifecycle** — stub-first / enrich / teardown `completed_marker`
   bump / recency / `complete` coupling paragraphs.

A war story that sits *inside* one of these phases (e.g. Phase 0.5's "~8 hook trips" story) is
compressed **without touching the adjacent contract bullet**. The compression edits prose only.

## Changes

### Change 1 — Collapse Phases 7 & 8 into one generic stub

Remove the corporate-stack specifics of Phases 7 and 8 entirely. Replace both phase bodies with a
single stub heading that keeps the ordinal anchors alive (no renumber — Phases 9–13, which include
the C2 contract refs, keep their numbers and every cross-reference to them stays valid). The stub
carries only the transferable meta-lesson:

> ### Phases 7 & 8 — stack-specific deploy/push tactics live in a feedback memory, not here
>
> Deploy and push gotchas tied to a particular stack — skip-validation flags when a deploy script
> blocks on cosmetic lint, rebase-before-push when a versioned artifact (e.g. a compose file) bumps
> on every PR — belong in your own feedback memory for that stack, not in this general skill. Keep
> this skill stack-agnostic.

**Nothing is written to a memory.** The docker/Teleport/`./deploy` specifics are corporate-fork
residue that does not apply on this machine or to the shipped plugin; capturing them to a personal
memory was considered and rejected.

**Cross-ref fix.** Phase 9 currently borrows a fact from Phase 7: "a direct push to `main`, which a
branch-protection ruleset rejects (the protection Phase 7 already notes)". After the collapse there
is no Phase 7 branch-protection note to point at. Inline the fact and drop the back-reference:
"...which a branch-protection ruleset rejects". This is the only dangling cross-ref the collapse
creates (verified by grepping for "Phase 7" and "Phase 8" references in the file).

### Change 2 — Compress the 16 war stories to one-clause tags

Each narrative compresses to `Past failure: <one clause>` — keep the concrete anchor (the specific
thing that went wrong is what makes a rule stick), cut the retelling. The rule and the "why" prose
around each story are unchanged; only the narrative sentences shrink.

Inventory (line numbers as of the 454-line file):

| Phase | Line | Story (compressed target keeps the bolded fact) |
|---|---|---|
| 0.5 | 117 | orchestrator tripped ~8 confidence/verify blocks |
| 1 | 130 | re-asked "select your approach" 4× — harness choice leaked out of the envelope |
| 2 (primitive-contract) | 143 | DistributedLock schema structurally impossible — `attribute_not_exists(PK)` non-reentrant, nested not parallel |
| 2 (clean-base) | 151 | removal PR inherited two unrelated docs from a polluted local `main` |
| 2.5 | 170 | ~20 turns debating queue-vs-lease-vs-hybrid as ad-hoc Q&A |
| 2.6 | 192 | migration defaulted to keeping legacy shims; had to be re-run "remove the shims" |
| 3a (manifest) | 239 | worker pushed a PR carrying two files from a polluted base |
| 3a (terminal state) | 242 | workers stopped after strictcode and "handed back to push", leaving work uncommitted |
| 4b (clean-break gate) | 277 | original shim rework happened because no independent check hunted the rationalised compat |
| 4b (trio) | 279 | spawned architect/debugger/ai-engineer trio at PR-review time instead of the toolkit six |
| 5 | 287 | (narrative) the disprove-premise pattern caught stale Slack pin-bar / design-artefact false alarms |
| 9 (first-line) | 338 | worker shipped a per-PR wiki PR because the suppression instruction was below the workflow steps |
| 9 (wiki delivery) | 348 | wiki agent reported two commits "done"; unpushed on local `main`, direct push rejected by ruleset |
| 12 (re-check) | 378 | CONFLICTING self-healed before the queued rebase instruction landed — stale on arrival |
| 12 (next-blocker) | 380 | unblocked PR-3 on a PR-2 that was actually broken (race surfaced on 2nd restart) |
| Stop-conditions | 430 | relabelled a prod-enable gate as "do not start / hard wall"; took two human turns to correct |

The Stop-conditions story at line 430 sits beside the approval-gate rule ("Model an approval-gate as
'pause-then-proceed', never as 'do not start'"). That rule sentence is **kept**; only its trailing
narrative compresses. This is adjacent to — not inside — the LOOP-STOP contract block, so the
no-touch region is unaffected.

## Verification

Mechanical, post-edit. **The primary gate is the region byte-diff (step 1), not the token greps.**
The planning-sequence found the token-grep alone is necessary-but-not-sufficient: a keyword like
`LOOP-STOP:` can survive a grep while a connective sentence the model relies on is clipped from the
same phase, turning a hook from a safety net into a silent stall generator with verification still
green. So the gate is "did the diff touch a no-touch line range," and the greps are a secondary
smoke test.

1. **PRIMARY GATE — the six no-touch regions are byte-identical to `origin/main`.** Run `git diff
   origin/main -- skills/agentic-loop/SKILL.md` and confirm **every** diff hunk falls in war-story
   prose or the Phase 7/8 block — **never** inside a no-touch region. The writing-plans step must
   pin each of the six regions to an exact anchor pair (its first and last line, quoted verbatim
   from `origin/main`), so "did the slim touch contract text" is a decidable question, not a
   judgment call. A hunk intersecting any pinned region fails the gate, regardless of what the
   token greps say.
2. **Secondary smoke test — contract tokens still present.** Grep the edited file for each (a
   missing one is a definite failure; a present one is *not* proof the region is intact — step 1
   is):
   - `LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete>`
   - the four category names in the Stop-conditions block (`hard-stop`, `approval-gate`,
     `awaiting-input`, `complete`)
   - `loop_stop_counts`
   - `completed_marker`
   - the stub JSON keys (`schema_version`, `session_id`, `status`, `authorising_prompt_raw`)
   - `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.sh"`
3. **Frontmatter description unchanged.** Diff the `description:` line against `origin/main` — it
   must be identical and still single-quoted.
4. **No dangling phase cross-refs.** Grep for "Phase 7" / "Phase 8" — the only surviving mentions
   should be the stub heading itself; no other text points at a removed phase.
5. **Line count drops with a sanity floor.** Report before (454) and after. No hard target, but a
   floor as a smell test: the 16 stories plus the ~20-line Phase 7/8 block are the bulk, so a
   genuine slim lands roughly a fifth shorter (~360 lines or below). A file that barely moved means
   the compression was timid or skipped — investigate, don't ship. The floor is a tripwire, not a
   number to game by deleting contract text.

## Out of scope

- No renumbering of phases (the leave-gap + stub decision avoids it; renumbering would touch the
  C2 contract refs at Phases 11–13 for no benefit).
- No new memory file (Change 1 rationale).
- No changes to the hooks, `hooks.json`, `install.sh`, or any `lib/` script — this spec edits one
  file, `skills/agentic-loop/SKILL.md`.
- Spec D (the superpowers construction-discipline seam) is the next spec, not this one.
