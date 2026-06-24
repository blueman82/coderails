# Spec B — Slim the agentic-loop skill: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `skills/agentic-loop/SKILL.md` from 454 lines to ~360 or below by collapsing vestigial corporate Phases 7 & 8 into a generic stub and compressing 16 "Past failure:" war stories to one-clause tags — without altering any C1/C2 contract text the Stop hooks rely on.

**Architecture:** A single-file prose edit. Three tasks, each ending in a verification gate. The **primary gate is a `git diff origin/main` region check** proving no edit hunk intersects any of the six pinned no-touch regions; token greps are a secondary smoke test. Task 1 (corporate collapse) and Task 2 (14 non-contract-adjacent stories) are low-risk; Task 3 isolates the 2 contract-adjacent stories (Phase 0.5, Stop-conditions) so the riskiest edits get their own reviewer gate.

**Tech Stack:** Markdown; bash (`git diff`, `grep`, `wc`, `sed`) for verification. No code, no test framework — the "tests" are the verification greps/diffs.

## Global Constraints

- **Edit exactly one file:** `skills/agentic-loop/SKILL.md`. No changes to hooks, `hooks.json`, `install.sh`, or any `lib/` script.
- **Six NO-TOUCH regions — byte-identical to `origin/main` at task end.** Pinned below by exact first/last anchor lines. No edit hunk may intersect any of them.
- **Frontmatter `description:` stays single-quoted and unchanged** (line 3; commit `e6e39dd` made it single-quoted for strict YAML — unquoting breaks skill loading).
- **No renumbering of phases.** Ordinal anchors stay; cross-refs to Phases 9–13 must remain valid.
- **No new memory file.** The docker/Teleport specifics are dropped, not relocated.
- **Auto-commit hook fires on Write/Edit.** Expect generic "via Edit" commits; collapse them with `git reset --soft <base>` + `git commit` before the task's final commit (never `git reset --hard`; `rm -rf` is blocked by the destructive-bash gate).

### The six NO-TOUCH regions (pinned anchors — verbatim from `origin/main`)

A region is "touched" if any `git diff origin/main` hunk overlaps the line span between (and including) its first and last anchor line. Verify each task against ALL six.

1. **Frontmatter description** — the single line beginning:
   `description: 'Multi-agent orchestration discipline. Load this skill IMMEDIATELY` … ending `…fire this skill aggressively rather than miss it.'`
2. **Phase -2 (stub-first)** — first: `### Phase -2 — Stub \`progress.json\` first (the literal first action)` … last: `…this is what lets the guard tell a genuinely-finished loop from a new one that re-armed it (see the teardown rule below).` (includes the JSON stub fenced block).
3. **Phase 0.5 LOOP-STOP bullet** — the single bullet beginning:
   `- End any stopping turn inside an active loop with a LOOP-STOP declaration line —` … ending `…also set \`progress.json\` \`status: "complete"\` and run the Phase 13 teardown.` (this bullet ONLY; the "why" paragraph below it in Phase 0.5 is editable — that is where the Task 3 story lives).
4. **Phase 13 KPI bullet** — the single bullet beginning:
   `- **LOOP-STOP declarations by category** —` … ending `…from hiding stalls behind a valid-looking tag.`
5. **Stop-conditions "Declaring the stop" block** — first: `**Declaring the stop (the LOOP-STOP contract).** Whichever class applies,` … last: `…The Phase 13 category counts are the audit on that.` (includes the four-category list `hard-stop`/`approval-gate`/`awaiting-input`/`complete`).
6. **Context-window persistence section** — the entire `## Context-window persistence` section, first: `## Context-window persistence` … last line before `## Stop conditions for the loop`: `…If a genuine stop condition (see below) is not met, keep going.` (no war stories live here, so the whole section is no-touch).

---

### Task 1: Collapse corporate Phases 7 & 8 into a generic stub

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` (replace the Phase 7 + Phase 8 block; fix one Phase 9 cross-ref)

**Interfaces:**
- Consumes: nothing.
- Produces: a single stub heading at the former Phase 7/8 location that keeps the ordinal anchors alive for downstream cross-refs.

- [ ] **Step 1: Replace the entire Phase 7 + Phase 8 block.**

Replace this block (currently the `### Phase 7 …` heading through the end of the Phase 8 paragraph that ends `…pollution must never enter the worker's base in the first place.`):

```
### Phase 7 — Skip-validation when cosmetic blockers trip deploy

When `./deploy` is blocked by black/isort/import-order failures AFTER the source-of-truth PR is already merged on main, that's deploy-script noise on cosmetic style — not a real blocker.

Use `./deploy --force --skip-drain --skip-validation`. Don't get stuck on it. Don't try to push a style fix to main (branch protection will reject direct push anyway). Don't open a one-line cosmetic PR mid-loop.

Memory: `feedback_deploy_skip_drain_default` already says skip-drain is the default; this extends to skip-validation in the same spirit.

### Phase 8 — Rebase before push on long parallel sessions

When a worktree's branch was created off main BEFORE the previous PR in the loop landed, its base will be stale. Before push, rebase:

```
cd <worktree>
git fetch origin
git rebase origin/main
```

The rebase will cleanly drop the auto-bumped `docker-compose.yml` version commit (it's already upstream). If the rebase has real conflicts in code, those are real and need resolution.

Without the rebase, push may still succeed but the PR will carry a duplicate docker-compose bump and confuse the diff review.

This rebase handles *staleness* (a base that fell behind as the loop's own PRs landed). It does NOT handle *pollution* (a local `main` carrying another session's commits) — that is the Phase 2 clean-base check's job, and the fix there is to branch workers off `origin/main`, not to rebase a polluted base onto itself. Staleness rebases away; pollution must never enter the worker's base in the first place.
```

with exactly this stub:

```
### Phases 7 & 8 — stack-specific deploy/push tactics live in a feedback memory, not here

Deploy and push gotchas tied to a particular stack — skip-validation flags when a deploy script blocks on cosmetic lint, rebase-before-push when a versioned artifact (e.g. a compose file) bumps on every PR — belong in your own feedback memory for that stack, not in this general skill. Keep this skill stack-agnostic.
```

*(Note for the implementer: the Phase 8 block contains a nested triple-backtick fence around the `git rebase` snippet. Use a sufficiently unique `old_string` for your edit tool — include the surrounding prose so the match is unambiguous — or replace in two passes. The deliverable is that the entire two-phase block above becomes the single stub above.)*

- [ ] **Step 2: Fix the Phase 9 cross-ref that points at the now-removed Phase 7.**

In the Phase 9 paragraph beginning `**Wiki commits are artifacts too`, change:

`…which a branch-protection ruleset rejects (the protection Phase 7 already notes).`

to:

`…which a branch-protection ruleset rejects.`

- [ ] **Step 3: Verify the corporate content is gone and no cross-ref dangles.**

```bash
cd /Users/harrison/Github/coderails
# Corporate specifics must be GONE (expect zero hits):
grep -nE "skip-validation|skip-drain|tsh ssh|docker-compose|\\./deploy|black/isort" skills/agentic-loop/SKILL.md
# 'Phase 7'/'Phase 8' should appear ONLY in the new stub heading (expect 1 line):
grep -n "Phase 7\|Phase 8" skills/agentic-loop/SKILL.md
```
Expected: first grep → no output. Second grep → exactly one line, the `### Phases 7 & 8 —` stub heading.

- [ ] **Step 4: Verify no NO-TOUCH region was touched (PRIMARY GATE).**

```bash
git --no-pager diff origin/main -- skills/agentic-loop/SKILL.md
```
Expected: every hunk falls in the Phase 7/8 block region or the single Phase 9 line. No hunk overlaps any of the six pinned regions. Eyeball each hunk's `@@` line ranges against the region anchors.

- [ ] **Step 5: Commit** (collapse any auto-commit first).

```bash
git reset --soft 50a0b10 2>/dev/null || true   # base = C2 merge; skip if already at a clean base
git add skills/agentic-loop/SKILL.md
git commit -m "refactor(agentic-loop): collapse corporate Phases 7 & 8 into a generic stub"
```
*(If other commits from this branch must be preserved, soft-reset only to fold the auto-commits for THIS task; the SDD controller manages the final squash.)*

---

### Task 2: Compress the 14 non-contract-adjacent war stories

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` (14 prose compressions in Phases 1, 2, 2.5, 2.6, 3a, 4b, 5, 9, 12)

**Interfaces:**
- Consumes: Task 1's output (file with the stub).
- Produces: 14 compressed `Past failure:` tags. None of these stories is inside a no-touch region.

Apply each edit below. Keep the rule and "why" prose that precedes each story; replace only the narrative. The compressed target is given verbatim — copy it, do not re-derive (this preserves the keeper fact and avoids over-compression).

- [ ] **Step 1: Phase 1 (harness leak).** Replace `Past failure: a real run re-asked "select your approach: /agentic-loop /loop /goal" four times because harness selection leaked out of the envelope and into plan negotiation.` with:
  `Past failure: a run re-asked "select your approach" 4× because harness choice leaked out of the envelope into plan negotiation.`

- [ ] **Step 2: Phase 2 (primitive-contract).** Replace `Past failure: a "wrap both call sites with a DistributedLock" schema was structurally impossible because the lock used \`attribute_not_exists(PK)\` non-reentrant semantics and the two sites were a nested call, not parallel — would have 100%-no-posted on every trigger. Pre-flight caught it by reading \`distributed_lock.py\` directly; the schema author hadn't.` with:
  `Past failure: a "wrap both sites with a DistributedLock" schema was impossible — the lock's \`attribute_not_exists(PK)\` semantics are non-reentrant and the sites were nested, not parallel; only reading the primitive's source caught it.`

- [ ] **Step 3: Phase 2 (clean-base).** Replace `Past failure: a removal PR's file list silently included two unrelated docs (\`durable-queue-design.md\` and an architecture-review doc) inherited from a polluted local \`main\` via the worker branching off it. Phase 12 caught it at the merge gate, but the fix cost a full close-and-rebuild cycle — new branch off \`origin/main\`, cherry-pick the real commits, reopen the PR, close the contaminated one. A clean-base check at loop start would have forced origin/main-based worktrees from the first spawn and avoided the rebuild entirely.` with:
  `Past failure: a removal PR silently carried two unrelated docs inherited from a polluted local \`main\`; it surfaced only at the merge gate and cost a full close-and-rebuild cycle.`

- [ ] **Step 4: Phase 2.5 (design debate).** Replace `Past failure: a real run spent ~20 turns debating queue-vs-lease-vs-hybrid as ad-hoc Q&A interleaved with the build — that decision should have been one design-agent artifact resolved once, before any PR work began.` with:
  `Past failure: a run spent ~20 turns debating queue-vs-lease-vs-hybrid as ad-hoc Q&A interleaved with the build — it should have been one design artifact resolved before any PR work.`

- [ ] **Step 5: Phase 2.6 (shim default).** Replace `Past failure: a migration defaulted to keeping legacy shims and bridges because the model reasoned the human wanted existing functionality preserved; the loop had to be re-invoked with an explicit "remove the shims" instruction — double the work instead of one clean migration.` with:
  `Past failure: a migration kept legacy shims because the model assumed the human wanted them; it had to be re-run with "remove the shims" — double the work.`

- [ ] **Step 6: Phase 3a (manifest).** Replace `Past failure: a worker pushed a PR whose file list silently included two files from a polluted base; nobody asserted scope before push, so it surfaced only at the merge gate and forced a rebuild.` with:
  `Past failure: a worker pushed a PR carrying two files from a polluted base — no pre-push scope assertion, so it surfaced only at the merge gate and forced a rebuild.`

- [ ] **Step 7: Phase 3a (terminal state).** Replace `Past failure: workers repeatedly stopped after running strictcode or an inline review and 'handed back to the orchestrator to push the PR', leaving the work uncommitted with no PR and forcing a resume cycle each time. Stating the terminal state as the artifact, not the sub-step, removes the premature hand-back.` with:
  `Past failure: workers stopped after strictcode and "handed back to push the PR", leaving work uncommitted with no PR — stating the terminal state as the artifact removes the premature hand-back.`

- [ ] **Step 8: Phase 4b (clean-break gate).** Replace `Past failure: the original shim rework happened precisely because no independent check hunted for the compat the author had rationalised as necessary.` with:
  `Past failure: the original shim rework happened because no independent check hunted the compat the author had rationalised as necessary.`

- [ ] **Step 9: Phase 4b (trio).** Leave as-is — `Past failure: spawned the architect/debugger/ai-engineer trio at PR-review time; corrected to the toolkit six.` is already a single clause. (No edit; listed so the inventory is complete.)

- [ ] **Step 10: Phase 5 (disprove-premise).** Replace `In a long multi-agent session this pattern caught false alarms (stale Slack pin-bar views and design artefacts mistaken for regressions). The cost of disproving is one tool call; the cost of shipping a fix to a non-bug is a PR, a deploy, a rollback, and trust.` with:
  `Past failure: this pattern caught false alarms — stale Slack pin-bar views and design artefacts mistaken for regressions. The cost of disproving is one tool call; the cost of shipping a fix to a non-bug is a PR, a deploy, a rollback, and trust.`

- [ ] **Step 11: Phase 9 (first-line).** Replace `Past failure: a worker shipped a per-PR wiki PR despite the suppression instruction being present, because the instruction was below the workflow steps. The next worker, with the same instruction moved to the top of their prompt, complied cleanly.` with:
  `Past failure: a worker shipped a per-PR wiki PR because the suppression instruction sat below the workflow steps; moving it to the top fixed it.`
  (Keep the trailing bold sentence `**Scope-suppression instructions go above scope-additive instructions in worker prompts.**` unchanged.)

- [ ] **Step 12: Phase 9 (wiki delivery).** Replace `Past failure: a wiki agent reported two commits "done"; they were on local \`main\`, unpushed, and \`main\` was ruleset-protected so a direct push was rejected. The orchestrator's origin check caught it; the fix was SHA-push → branch → PR → squash-merge → non-destructive \`main\` restore. Trusting the "committed" ping would have stranded the docs locally and left the next loop on a polluted base.` with:
  `Past failure: a wiki agent reported two commits "done" that were unpushed on local \`main\` (ruleset-protected, so a direct push was rejected); the origin check caught it before the docs were stranded.`

- [ ] **Step 13: Phase 12 (re-check).** Replace `Past failure: orchestrator read CONFLICTING state when the worker first reported "ready", queued a rebase instruction, but by the time the worker received it the conflict had self-healed via an intervening merge commit — the rebase instruction was stale on arrival and triggered redundant work. The cost of one extra \`gh pr view\` between report and instruction is small.` with:
  `Past failure: a CONFLICTING state self-healed via an intervening merge before the queued rebase instruction landed — stale on arrival, it triggered redundant work. One extra \`gh pr view\` between report and instruction is cheap.`

- [ ] **Step 14: Phase 12 (next-blocker).** Replace `Past failure mode: agent reports PR-2 verified, you unblock PR-3, then PR-2 was actually broken (race condition surfaced only on second container restart), and PR-3 is now stacked on a bad base.` with:
  `Past failure: an agent reported PR-2 verified, PR-3 was unblocked, then PR-2 proved broken (race surfaced on the 2nd restart) — PR-3 stacked on a bad base.`

- [ ] **Step 15: Verify NO-TOUCH regions untouched (PRIMARY GATE) + tokens present.**

```bash
cd /Users/harrison/Github/coderails
git --no-pager diff origin/main -- skills/agentic-loop/SKILL.md | grep -nE "^@@"   # inspect hunk ranges
# Secondary smoke test — every contract token still present:
grep -c "LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete>" skills/agentic-loop/SKILL.md
grep -c "loop_stop_counts" skills/agentic-loop/SKILL.md
grep -c "completed_marker" skills/agentic-loop/SKILL.md
grep -c 'agentic_loop_path.sh' skills/agentic-loop/SKILL.md
```
Expected: no diff hunk overlaps any of the six pinned regions (Task 2 edits are all in Phases 1, 2, 2.5, 2.6, 3a, 4b, 5, 9, 12 — none of which is a no-touch region). Each `grep -c` ≥ 1.

- [ ] **Step 16: Commit.**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "refactor(agentic-loop): compress 14 non-contract war stories to one-clause tags"
```

---

### Task 3: Compress the 2 contract-adjacent war stories (highest risk)

**Files:**
- Modify: `skills/agentic-loop/SKILL.md` (Phase 0.5 "why" paragraph; Stop-conditions approval-gate paragraph)

**Interfaces:**
- Consumes: Task 2's output.
- Produces: the final two compressions. Both sit in phases that ALSO contain a no-touch region; the edit must stay strictly outside it.

- [ ] **Step 1: Phase 0.5 (orchestrator self-trip) — edit the "why" paragraph ONLY, not the LOOP-STOP bullet above it.** Replace `Past failure: in a real run the orchestrator tripped ~8 confidence-label / verify-loop blocks, each one a manual turn the user had to clear.` with:
  `Past failure: an orchestrator tripped ~8 confidence/verify blocks in one run — each a manual turn to clear.`
  This text is in the paragraph beginning `The why: a factory whose conductor keeps tripping the wires…`, which is BELOW no-touch region #3 (the LOOP-STOP bullet). Do not touch the bullet.

- [ ] **Step 2: Stop-conditions (prod-gate mislabel) — edit the approval-gate paragraph ONLY, not the "Declaring the stop" block below it.** Replace `Past failure: a real run relabelled a prod-enable gate as "do not start / hard wall", which mis-stated its own terminal state and took two human turns to correct.` with:
  `Past failure: a run relabelled a prod-enable gate as "do not start / hard wall" and took two human turns to correct.`
  This is in the paragraph ending `…The gate is a pause point inside the envelope, not the edge of it.`, which is ABOVE no-touch region #5 (the "Declaring the stop" block). Do not touch that block.

- [ ] **Step 3: PRIMARY GATE — prove the six no-touch regions are byte-identical to origin/main.**

```bash
cd /Users/harrison/Github/coderails
git --no-pager diff origin/main -- skills/agentic-loop/SKILL.md
```
Inspect EVERY hunk. Confirm none overlaps:
- the frontmatter `description:` line,
- the Phase -2 block,
- the Phase 0.5 LOOP-STOP bullet (the Task-3 Step-1 edit is in the paragraph after it),
- the Phase 13 KPI bullet,
- the Stop-conditions "Declaring the stop" block (the Task-3 Step-2 edit is in the paragraph before it),
- the whole `## Context-window persistence` section.

If any hunk intersects a region, REVERT that hunk and report — the gate has failed regardless of token greps.

- [ ] **Step 4: Secondary smoke test — contract tokens + frontmatter + line-count floor.**

```bash
cd /Users/harrison/Github/coderails
# Tokens present (each ≥1):
for t in "LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete>" "loop_stop_counts" "completed_marker" "schema_version" "authorising_prompt_raw" 'agentic_loop_path.sh'; do
  printf '%s -> ' "$t"; grep -c -- "$t" skills/agentic-loop/SKILL.md
done
# Frontmatter description identical to origin/main (expect no output):
diff <(git show origin/main:skills/agentic-loop/SKILL.md | sed -n '3p') <(sed -n '3p' skills/agentic-loop/SKILL.md)
# Line-count floor — expect ~360 or below:
wc -l skills/agentic-loop/SKILL.md
```
Expected: every token count ≥1; the `diff` produces no output (description unchanged, still single-quoted); `wc -l` is roughly a fifth below 454 (≈360 or lower). A file barely shorter than 454 means compression was timid — investigate before committing.

- [ ] **Step 5: Commit.**

```bash
git add skills/agentic-loop/SKILL.md
git commit -m "refactor(agentic-loop): compress the 2 contract-adjacent war stories"
```

---

## Self-Review

**Spec coverage:**
- Change 1 (collapse Phases 7 & 8 + Phase 9 cross-ref) → Task 1. ✓
- Change 2 (compress 16 war stories) → Tasks 2 (14) + 3 (2). 14 + 2 = 16. ✓ (Step 9's trio story is already one clause — counted, no edit.)
- No-touch constraint (6 regions) → Global Constraints + each task's primary-gate step. ✓
- Verification: region byte-diff primary gate, token smoke test, frontmatter diff, no dangling cross-ref, line-count floor → distributed across Task 1 Step 3–4, Task 2 Step 15, Task 3 Steps 3–4. ✓
- Out-of-scope (no renumber, no memory, single file) → Global Constraints. ✓

**Placeholder scan:** No TBD/TODO. Every prose edit shows exact old→new text. Verification steps show exact commands + expected output. ✓

**Type consistency:** N/A (prose). Cross-checked: every "replace X with Y" quotes X verbatim from the 454-line file (anchors captured via grep/sed this session). The base SHA for soft-reset is `50a0b10` (the C2 merge, current `origin/main`). ✓
