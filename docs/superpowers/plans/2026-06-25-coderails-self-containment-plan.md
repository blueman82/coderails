# Coderails Self-Containment Implementation Plan

**Goal:** Vendor superpowers' 12 missing core development-workflow skills into the `coderails:` namespace, add a SessionStart bootstrap hook, and rewire `agentic-loop` to reference the vendored skills — so coderails depends on superpowers for nothing.

**Architecture:** Two phases. Phase 1 (PRs 1–6) is mechanical copy + rebrand + register; it does not touch `agentic-loop`, so it cannot regress the autonomous loop. Phase 2 (PR 7) is an additive one-line reference in Phase 3/3a of `agentic-loop` plus stale-ref cleanup; it leaves the six C1/C2 no-touch regions byte-identical. Skills land in `skills/<name>/` inside the coderails repo; the bootstrap lands in `hooks/scripts/inject_bootstrap.sh` with a new `SessionStart` block in `hooks/hooks.json`.

## Global Constraints

- Source tree: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/` (v6.0.3, verified 2026-06-25).
- Destination: `/Users/harrison/Github/coderails/skills/<skill-name>/`.
- Rebrand rule 1 — namespace: every `superpowers:<skill>` → `coderails:<skill>` in every shipped file.
- Rebrand rule 2 — body scrub: `grep -ri 'superpowers' <skill-dir>` must return zero hits in shipped files before the PR is opened.
- Rebrand rule 3 — foreign-skill refs (`elements-of-style:*`): drop the optional cross-plugin reference, keep the behaviour.
- Rebrand rule 4 — cruft drop: `CREATION-LOG.md`, `test-pressure-*.md`, `writing-skills/examples/CLAUDE_MD_TESTING.md` not shipped.
- Rebrand rule 5 — path rewrites (non-markdown): `.superpowers/` → `.coderails/` in scripts, `SUPERPOWERS_*` variable names → `CODERAILS_*`.
- Rebrand rule 6 — `references/` relative paths: `../using-superpowers/references/` → `../using-coderails/references/` in any file that contains the old path.
- `inject_bootstrap.sh` must be bash-3.2-safe (macOS); no external tools beyond `jq` already present in coderails hooks.
- C1/C2 six no-touch regions in `agentic-loop/SKILL.md` stay byte-identical: frontmatter `description`, Phase -2, Phase 0.5 LOOP-STOP bullet, Phase 13 KPI bullet, Stop-conditions LOOP-STOP block, Context-window-persistence lifecycle section.
- Every PR: `grep -rIi superpowers <dirs-touched>` returns nothing in shipped files before push.

---

## File Map (all files created or modified across all PRs)

| File | PR | Action |
|---|---|---|
| `skills/using-git-worktrees/SKILL.md` | PR1 | copy + rebrand |
| `skills/requesting-code-review/SKILL.md` | PR1 | copy + rebrand |
| `skills/requesting-code-review/code-reviewer.md` | PR1 | copy + rebrand |
| `skills/receiving-code-review/SKILL.md` | PR1 | copy + rebrand |
| `skills/finishing-a-development-branch/SKILL.md` | PR1 | copy + rebrand |
| `skills/subagent-driven-development/SKILL.md` | PR2 | copy + rebrand (9 superpowers refs) |
| `skills/subagent-driven-development/implementer-prompt.md` | PR2 | copy + rebrand |
| `skills/subagent-driven-development/task-reviewer-prompt.md` | PR2 | copy + rebrand |
| `skills/subagent-driven-development/scripts/sdd-workspace` | PR2 | copy + path rebrand (`.superpowers/sdd` → `.coderails/sdd`) |
| `skills/subagent-driven-development/scripts/task-brief` | PR2 | copy + path rebrand |
| `skills/subagent-driven-development/scripts/review-package` | PR2 | copy + path rebrand |
| `skills/executing-plans/SKILL.md` | PR2 | copy + rebrand + semantic rewrite line 14 + line 36 + lines 68-70 + ref path fix |
| `skills/brainstorming/SKILL.md` | PR3 | copy + rebrand (drop elements-of-style ref line 108; fix docs/superpowers/specs path lines 29, 106; fix spec-document-reviewer-prompt.md line 7) |
| `skills/brainstorming/spec-document-reviewer-prompt.md` | PR3 | copy + rebrand (line 7 path) |
| `skills/brainstorming/visual-companion.md` | PR3 | copy + rebrand (5 `.superpowers/brainstorm/` path refs) |
| `skills/brainstorming/scripts/server.cjs` | PR3 | copy + rebrand (SUPERPOWERS_BRAND_IMAGE_URL removed; brand strings → coderails; Decision Ledger feature) |
| `skills/brainstorming/scripts/start-server.sh` | PR3 | copy + rebrand (lines 9/117/120/121: `.superpowers/brainstorm/` → `.coderails/brainstorm/`) |
| `skills/brainstorming/scripts/stop-server.sh` | PR3 | copy + rebrand (line 6 comment) |
| `skills/brainstorming/scripts/frame-template.html` | PR3 | copy + rebrand (`<title>` → coderails) |
| `skills/brainstorming/scripts/helper.js` | PR3 | copy (inspect for superpowers refs) |
| `skills/dispatching-parallel-agents/SKILL.md` | PR4 | copy + rebrand |
| `skills/systematic-debugging/SKILL.md` | PR4 | copy + rebrand (lines 179, 287, 288) |
| `skills/systematic-debugging/condition-based-waiting-example.ts` | PR4 | copy (no superpowers refs) |
| `skills/systematic-debugging/condition-based-waiting.md` | PR4 | copy (no superpowers refs) |
| `skills/systematic-debugging/defense-in-depth.md` | PR4 | copy (no superpowers refs) |
| `skills/systematic-debugging/find-polluter.sh` | PR4 | copy (no superpowers refs) |
| `skills/systematic-debugging/root-cause-tracing.md` | PR4 | copy (no superpowers refs) |
| `skills/verification-before-completion/SKILL.md` | PR5 | copy + rebrand |
| `skills/writing-skills/SKILL.md` | PR5 | copy + rebrand (lines 12, 18, 283, 284, 393; ref path line 12 → `../using-coderails/references/`) |
| `skills/writing-skills/testing-skills-with-subagents.md` | PR5 | copy + rebrand illustrative refs (line 13) |
| `skills/writing-skills/anthropic-best-practices.md` | PR5 | copy (inspect for superpowers refs) |
| `skills/writing-skills/graphviz-conventions.dot` | PR5 | copy (inspect) |
| `skills/writing-skills/persuasion-principles.md` | PR5 | copy (inspect) |
| `skills/writing-skills/render-graphs.js` | PR5 | copy (inspect) |
| `skills/using-coderails/SKILL.md` | PR6 | copy from using-superpowers + full rebrand |
| `skills/using-coderails/references/antigravity-tools.md` | PR6 | copy + rebrand (2 superpowers refs) |
| `skills/using-coderails/references/claude-code-tools.md` | PR6 | copy + inspect |
| `skills/using-coderails/references/codex-tools.md` | PR6 | copy + inspect |
| `skills/using-coderails/references/copilot-tools.md` | PR6 | copy + inspect |
| `skills/using-coderails/references/gemini-tools.md` | PR6 | copy + rebrand (2 superpowers refs) |
| `skills/using-coderails/references/pi-tools.md` | PR6 | copy + inspect |
| `hooks/scripts/tests/inject_bootstrap.test.sh` | PR6 | **create first (TDD)** |
| `hooks/scripts/inject_bootstrap.sh` | PR6 | create (bash-3.2-safe, reads SKILL.md, emits additionalContext JSON) |
| `hooks/hooks.json` | PR6 | add SessionStart block |
| `install.sh` | PR6 | add `hooks/scripts/inject_bootstrap.sh` to chmod list (after line 329) |
| `uninstall.sh` | PR6 | no script-specific action needed (chmod is not reversed; hook is deregistered by /plugin uninstall) |
| `skills/agentic-loop/SKILL.md` | PR7 | add SDD reference line in Phase 3 worker-description bullet (after line 239); fix line 13 and 134 claude-guardrails refs |

---

## PR 1 — Tier A Leaves: using-git-worktrees, requesting-code-review, receiving-code-review, finishing-a-development-branch

**blockedBy:** nothing (no in-graph dependencies on vendored skills)

**Scope:** 5 files created in `skills/`. No hooks, no install.sh, no agentic-loop.

### Cross-references to rewrite (verified by grep)

- `using-git-worktrees/SKILL.md`: zero `superpowers:` namespace refs (verified — grep returned no output).
- `requesting-code-review/SKILL.md`: zero `superpowers:` namespace refs. One path in an example (`docs/superpowers/plans/deployment-plan.md`, line 60) — rewrite to `docs/coderails/plans/deployment-plan.md` (it is an illustrative placeholder, not a functional path; the rebrand scrub will flag it).
- `requesting-code-review/code-reviewer.md`: zero `superpowers:` refs (verified).
- `receiving-code-review/SKILL.md`: zero `superpowers:` refs (verified).
- `finishing-a-development-branch/SKILL.md`: zero `superpowers:` refs (verified).

### Tasks

#### Task 1.1 — Copy and rebrand Tier A leaves

**Files to create:**
- `skills/using-git-worktrees/SKILL.md`
- `skills/requesting-code-review/SKILL.md`
- `skills/requesting-code-review/code-reviewer.md`
- `skills/receiving-code-review/SKILL.md`
- `skills/finishing-a-development-branch/SKILL.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/<skill-name>/`

**Construction method:** inspection (markdown — no testable code). Steps:

1. For each skill, copy the source file(s) into `skills/<skill-name>/` in the coderails repo.
2. In each copied file, perform the namespace rewrite: replace every occurrence of `superpowers:` with `coderails:` (including inside prose, not just in structured fields).
3. In `requesting-code-review/SKILL.md` line 60 example path, replace `docs/superpowers/plans/` with `docs/coderails/plans/`.
4. Verify frontmatter `name:` field in each SKILL.md does not contain "superpowers" and matches the skill directory name.
5. Run scrub: `grep -rIi 'superpowers' skills/using-git-worktrees skills/requesting-code-review skills/receiving-code-review skills/finishing-a-development-branch` — must return zero output.

**Interfaces produced:**
- `skills/requesting-code-review/code-reviewer.md` — path used by PR2's `subagent-driven-development/SKILL.md` line 270 (`../requesting-code-review/code-reviewer.md`); relative path must resolve correctly from the sibling skill directory.

**Verify criteria:**
```
grep -rIi 'superpowers' \
  skills/using-git-worktrees \
  skills/requesting-code-review \
  skills/receiving-code-review \
  skills/finishing-a-development-branch
# Expected: no output (zero matches)

# Frontmatter check:
grep '^name:' skills/using-git-worktrees/SKILL.md        # → name: using-git-worktrees
grep '^name:' skills/requesting-code-review/SKILL.md     # → name: requesting-code-review
grep '^name:' skills/receiving-code-review/SKILL.md      # → name: receiving-code-review
grep '^name:' skills/finishing-a-development-branch/SKILL.md  # → name: finishing-a-development-branch
```

**Manifest:** 5 new files, all under `skills/`. Zero existing files modified.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only files under `skills/using-git-worktrees/`, `skills/requesting-code-review/`, `skills/receiving-code-review/`, `skills/finishing-a-development-branch/`. If any other path appears, STOP.

---

## PR 2 — Tier B Executors: subagent-driven-development, executing-plans

**blockedBy:** PR1 (both skills reference the Tier A leaves by namespace; Tier A must exist before the scrub is meaningful and before a reviewer can validate relative path references)

**Scope:** 8 files created in `skills/`. No hooks, no install.sh, no agentic-loop.

### Cross-references to rewrite (verified by grep)

**subagent-driven-development/SKILL.md** — 9 `superpowers:` occurrences (highest rebrand-error risk):
- Line 66: `"Use superpowers:finishing-a-development-branch"` (Graphviz label) → `"Use coderails:finishing-a-development-branch"`
- Line 81: `"Use superpowers:finishing-a-development-branch"` (Graphviz edge label) → `"Use coderails:finishing-a-development-branch"`
- Line 254: `$(git rev-parse --show-toplevel)/.superpowers/sdd/progress.md` → `$(git rev-parse --show-toplevel)/.coderails/sdd/progress.md`
- Line 270: `use superpowers:requesting-code-review's` → `use coderails:requesting-code-review's`
- Line 277: `docs/superpowers/plans/feature-plan.md` (example path) → `docs/coderails/plans/feature-plan.md`
- Line 286: `~/.config/superpowers/hooks/` (example path in dialogue) → `~/.config/coderails/hooks/`
- Line 409: `superpowers:using-git-worktrees` → `coderails:using-git-worktrees`
- Line 410: `superpowers:writing-plans` → `coderails:writing-plans`
- Line 411: `superpowers:requesting-code-review` → `coderails:requesting-code-review`
- Line 412: `superpowers:finishing-a-development-branch` → `coderails:finishing-a-development-branch`
- Line 415: `superpowers:test-driven-development` → `coderails:test-driven-development`
- Line 418: `superpowers:executing-plans` → `coderails:executing-plans`

**subagent-driven-development/scripts/sdd-workspace** — line 19: `dir="$root/.superpowers/sdd"` → `dir="$root/.coderails/sdd"`

**subagent-driven-development/scripts/task-brief** — line 7 comment: `.superpowers/sdd/task-<N>-brief.md` → `.coderails/sdd/task-<N>-brief.md`

**subagent-driven-development/scripts/review-package** — line 8 comment: `.superpowers/sdd/review-<base7>..<head7>.diff` → `.coderails/sdd/review-<base7>..<head7>.diff`

**executing-plans/SKILL.md** — 5 `superpowers:` occurrences:
- Line 14: **Semantic rewrite required** — the sentence "Tell your human partner that Superpowers works much better with access to subagents… use `superpowers:subagent-driven-development` instead of this skill" is self-referential in a coderails-only install. Rewrite to: "This skill executes a plan in the current session without subagents. If subagents are available in your session, use `coderails:subagent-driven-development` instead — it provides higher-quality output by dispatching each task to an isolated worker with its own context." (Drop the platform list and the `../using-superpowers/references/` cross-link entirely — the reference dir will exist as `../using-coderails/references/` after PR6, but the sentence's function is the altitude distinction, not the platform listing.)
- Line 36: `superpowers:finishing-a-development-branch` → `coderails:finishing-a-development-branch`
- Line 68: `superpowers:using-git-worktrees` → `coderails:using-git-worktrees`
- Line 69: `superpowers:writing-plans` → `coderails:writing-plans`
- Line 70: `superpowers:finishing-a-development-branch` → `coderails:finishing-a-development-branch`

### Tasks

#### Task 2.1 — Copy and rebrand subagent-driven-development

**Files to create:**
- `skills/subagent-driven-development/SKILL.md`
- `skills/subagent-driven-development/implementer-prompt.md`
- `skills/subagent-driven-development/task-reviewer-prompt.md`
- `skills/subagent-driven-development/scripts/sdd-workspace`
- `skills/subagent-driven-development/scripts/task-brief`
- `skills/subagent-driven-development/scripts/review-package`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/subagent-driven-development/`

**Construction method:** inspection + scrub (markdown + shell scripts with path strings — no logic to test). Steps:

1. Copy all six files (create `skills/subagent-driven-development/scripts/` directory).
2. Apply all 12 namespace and path rewrites listed above (each has an exact line reference — check each one).
3. In the Graphviz diagram (lines 66, 81) verify the graph still renders syntactically after the label rewrites (no closing quote dropped).
4. Run scrub: `grep -rIi 'superpowers' skills/subagent-driven-development` — must return zero output.
5. Verify frontmatter `name: subagent-driven-development`.

**Interfaces produced:**
- `skills/subagent-driven-development/implementer-prompt.md` — path consumed by PR7's agentic-loop reference addition; the relative reference `../subagent-driven-development/implementer-prompt.md` is used by the SDD skill description itself, not by agentic-loop directly.
- `skills/subagent-driven-development/scripts/sdd-workspace` — shell script; the workspace dir it creates is `.coderails/sdd/` (post-rebrand); progress tracking in subagent builds reads from this path.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/subagent-driven-development
# Expected: no output

grep '^name:' skills/subagent-driven-development/SKILL.md
# Expected: name: subagent-driven-development

# Spot-check key rewrites:
grep 'coderails:finishing-a-development-branch' skills/subagent-driven-development/SKILL.md | wc -l
# Expected: 4 (lines 66, 81, 412 — two graphviz + two prose refs)

grep '\.coderails/sdd' skills/subagent-driven-development/scripts/sdd-workspace
# Expected: 1 match (dir="$root/.coderails/sdd")
```

**Manifest:** 6 new files under `skills/subagent-driven-development/`. Zero existing files modified.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only files under `skills/subagent-driven-development/`. If any other path appears, STOP.

---

#### Task 2.2 — Copy, rebrand, and semantic-rewrite executing-plans

**Files to create:**
- `skills/executing-plans/SKILL.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/executing-plans/SKILL.md`

**Construction method:** inspection + scrub. Steps:

1. Copy the file to `skills/executing-plans/SKILL.md`.
2. Rewrite line 14 with the altitude-distinction prose (exact replacement shown in cross-references section above — drop the `../using-superpowers/references/` link, replace with the altitude explanation).
3. Rewrite line 36: `superpowers:finishing-a-development-branch` → `coderails:finishing-a-development-branch`.
4. Rewrite lines 68-70: all three `superpowers:` namespace refs → `coderails:`.
5. Run scrub: `grep -rIi 'superpowers' skills/executing-plans` — must return zero output.
6. Verify frontmatter `name: executing-plans`.
7. Read the rewritten line 14 and confirm: no self-referential recommender ("use this skill instead of itself"), no dead `../using-superpowers/references/` link, altitude distinction (parallel session vs same-session) is clear.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/executing-plans
# Expected: no output

grep '^name:' skills/executing-plans/SKILL.md
# Expected: name: executing-plans

# Confirm altitude rewrite landed (should contain subagent-driven-development ref):
grep 'coderails:subagent-driven-development' skills/executing-plans/SKILL.md
# Expected: 1 match (line 14 semantic rewrite)

grep 'coderails:finishing-a-development-branch' skills/executing-plans/SKILL.md | wc -l
# Expected: 2 (lines 36 and 70)
```

**Manifest:** 1 new file: `skills/executing-plans/SKILL.md`. Zero existing files modified.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only `skills/executing-plans/SKILL.md`. If any other path appears, STOP.

---

## PR 3 — Brainstorming (visual companion + Decision Ledger)

**blockedBy:** nothing (brainstorming's in-graph deps are `writing-plans`, already present in coderails). Highest-effort PR.

**Scope:** 8 files created under `skills/brainstorming/` and `skills/brainstorming/scripts/`. No hooks, no install.sh, no agentic-loop.

### Cross-references to rewrite (verified by grep)

**brainstorming/SKILL.md:**
- Line 29: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` → `docs/coderails/specs/YYYY-MM-DD-<topic>-design.md`
- Line 106: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` → `docs/coderails/specs/YYYY-MM-DD-<topic>-design.md`
- Line 108: `Use elements-of-style:writing-clearly-and-concisely skill if available` → drop this line (foreign-skill ref; behaviour preserved by the prose surrounding it).

**brainstorming/spec-document-reviewer-prompt.md:**
- Line 7: `docs/superpowers/specs/` → `docs/coderails/specs/`

**brainstorming/visual-companion.md** — 5 `.superpowers/brainstorm/` path refs:
- Line 42: `".../project/.superpowers/brainstorm/..."` → `.../project/.coderails/brainstorm/...`
- Line 43: same pattern
- Line 56: `.superpowers/brainstorm/` (two occurrences in the sentence) → `.coderails/brainstorm/`
- Line 58: `.superpowers/brainstorm/` (two occurrences) → `.coderails/brainstorm/`; also `.superpowers/` at end of sentence → `.coderails/`
- Line 293: `.superpowers/brainstorm/` → `.coderails/brainstorm/`

**brainstorming/scripts/server.cjs:**
- Line 106: `const SUPERPOWERS_BRAND_IMAGE_URL = 'https://primeradiant.com/brand/superpowers-visual-brainstorming-logo.png';` → remove this variable; replace all downstream uses with an empty string or remove the logo `<img>` tag.
- Line 251: brand div containing `https://github.com/obra/superpowers` and brand text → replace anchor href with `https://github.com/obra/coderails` (or remove the external link), brand text → `coderails`.
- Add the **Decision Ledger** feature: a persistent sidebar panel that records each design decision (question posed → chosen option → rationale) as an append-only ledger. Implementation: (a) server.cjs must serve an additional `/ledger-entry` POST endpoint that appends a JSON record to `$STATE_DIR/decision-ledger.jsonl`; (b) frame-template.html must render the ledger panel (read via a `/ledger` GET endpoint); (c) the ledger entries must survive server restarts (they persist in `$STATE_DIR`). The ledger records only decisions that Claude explicitly marks with `DECISION:` prefix in the brainstorm output; all other output renders in the main canvas.

**brainstorming/scripts/start-server.sh:**
- Line 9 comment: `<path>/.superpowers/brainstorm/` → `<path>/.coderails/brainstorm/`
- Line 117: `SESSION_DIR="${PROJECT_DIR}/.superpowers/brainstorm/${SESSION_ID}"` → `SESSION_DIR="${PROJECT_DIR}/.coderails/brainstorm/${SESSION_ID}"`
- Line 120: `BRAINSTORM_PORT_FILE="${PROJECT_DIR}/.superpowers/brainstorm/.last-port"` → `BRAINSTORM_PORT_FILE="${PROJECT_DIR}/.coderails/brainstorm/.last-port"`
- Line 121: `BRAINSTORM_TOKEN_FILE="${PROJECT_DIR}/.superpowers/brainstorm/.last-token"` → `BRAINSTORM_TOKEN_FILE="${PROJECT_DIR}/.coderails/brainstorm/.last-token"`

**brainstorming/scripts/stop-server.sh:**
- Line 6 comment: `.superpowers/` → `.coderails/`

**brainstorming/scripts/frame-template.html:**
- `<title>` tag → `coderails brainstorming`
- Add the Decision Ledger panel HTML (fetches `/ledger` on load; renders entries as a numbered list with question/answer/rationale rows).

### Tasks

#### Task 3.1 — Copy and rebrand markdown and shell files

**Files to create:**
- `skills/brainstorming/SKILL.md`
- `skills/brainstorming/spec-document-reviewer-prompt.md`
- `skills/brainstorming/visual-companion.md`
- `skills/brainstorming/scripts/stop-server.sh`
- `skills/brainstorming/scripts/start-server.sh`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/brainstorming/`

**Construction method:** inspection + scrub. Steps:

1. Copy the five files (create `skills/brainstorming/scripts/` directory).
2. Apply all path and namespace rewrites listed above for each file.
3. In `SKILL.md` line 108: remove the `elements-of-style:` reference line entirely.
4. Run scrub: `grep -rIi 'superpowers' skills/brainstorming/SKILL.md skills/brainstorming/spec-document-reviewer-prompt.md skills/brainstorming/visual-companion.md skills/brainstorming/scripts/stop-server.sh skills/brainstorming/scripts/start-server.sh` — must return zero output.

**Verify criteria:**
```
grep -rIi 'superpowers' \
  skills/brainstorming/SKILL.md \
  skills/brainstorming/spec-document-reviewer-prompt.md \
  skills/brainstorming/visual-companion.md \
  skills/brainstorming/scripts/stop-server.sh \
  skills/brainstorming/scripts/start-server.sh
# Expected: no output

grep '\.coderails/brainstorm/' skills/brainstorming/visual-companion.md | wc -l
# Expected: 5 (all five path refs rewritten)

grep '\.coderails/brainstorm/' skills/brainstorming/scripts/start-server.sh | wc -l
# Expected: 4 (lines 9 comment, 117, 120, 121)
```

---

#### Task 3.2 — Implement visual companion server with Decision Ledger (TDD)

**Files to create:**
- `skills/brainstorming/scripts/server.cjs`
- `skills/brainstorming/scripts/frame-template.html`
- `skills/brainstorming/scripts/helper.js`

**Source base:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/brainstorming/scripts/`

**Construction method:** Use `coderails:test-driven-development` for the Decision Ledger additions; the base copy (before the ledger feature) verified by running the server.

Steps — base copy and rebrand first:

1. Copy `server.cjs`, `frame-template.html`, `helper.js` from the source.
2. In `server.cjs`:
   a. Remove line 106 (`SUPERPOWERS_BRAND_IMAGE_URL` constant) and any `<img>` rendering that references it.
   b. Rewrite line 251's brand div: change the anchor href to `https://github.com/obra/coderails`; change brand text to `coderails`.
3. In `frame-template.html`: update `<title>` to `coderails brainstorming`.
4. Run scrub: `grep -rIi 'superpowers' skills/brainstorming/scripts/server.cjs skills/brainstorming/scripts/frame-template.html skills/brainstorming/scripts/helper.js` — must return zero output.

Steps — Decision Ledger (TDD, write test first):

The Decision Ledger requires three additions to `server.cjs` and one to `frame-template.html`:
- `POST /ledger-entry` endpoint: body `{"question": "...", "choice": "...", "rationale": "..."}` → appends a JSONL record to `$STATE_DIR/decision-ledger.jsonl` → returns `{"ok": true}`.
- `GET /ledger` endpoint: reads `$STATE_DIR/decision-ledger.jsonl` → returns JSON array of objects in insertion order; returns `[]` if file absent.
- `frame-template.html` ledger panel: on page load, calls `GET /ledger`, renders each entry as `<dt>Q: {question}</dt><dd>Chose: {choice} — {rationale}</dd>`.

TDD construction sequence:
1. Write a failing integration test as a Node.js script saved alongside (`server.test.cjs` — **do not ship**; used only during build): starts the server against a temp `STATE_DIR`, POSTs a ledger entry, GETs `/ledger`, asserts the entry appears. Run it: `node server.test.cjs` → expect a failure (endpoints not yet added).
2. Add the `POST /ledger-entry` endpoint to `server.cjs`. Run test: expect partial pass (GET still missing or fails).
3. Add the `GET /ledger` endpoint. Run test: expect full pass.
4. Add ledger panel HTML to `frame-template.html`. Launch the server manually (`node server.cjs --port 9999`) and verify the page loads without JS errors (check browser console or curl the HTML for the ledger panel element).
5. Delete `server.test.cjs` (build artifact, not shipped).

**Interfaces produced:**
- `POST /ledger-entry` endpoint: `{question: string, choice: string, rationale: string}` → `{ok: true}`
- `GET /ledger` endpoint: returns `Array<{question: string, choice: string, rationale: string, timestamp: string}>`
- Session dir path: `$PROJECT_DIR/.coderails/brainstorm/$SESSION_ID/` (set by `start-server.sh`; `server.cjs` reads `STATE_DIR` from env)

**Verify criteria:**
```
grep -rIi 'superpowers' skills/brainstorming/scripts/server.cjs \
  skills/brainstorming/scripts/frame-template.html \
  skills/brainstorming/scripts/helper.js
# Expected: no output

# Functional: launch server, verify it serves
STATE_DIR=$(mktemp -d) node skills/brainstorming/scripts/server.cjs --port 9998 &
sleep 1
curl -s http://localhost:9998/ledger   # → []
curl -s -X POST http://localhost:9998/ledger-entry \
  -H 'Content-Type: application/json' \
  -d '{"question":"q1","choice":"c1","rationale":"r1"}'  # → {"ok":true}
curl -s http://localhost:9998/ledger   # → [{"question":"q1","choice":"c1","rationale":"r1",...}]
kill %1
```

**Manifest:** 3 new files under `skills/brainstorming/scripts/`. Zero existing files modified.

**Pre-push scope assertion (PR3 combined):** `git diff origin/main --name-only` must show only files under `skills/brainstorming/`. If any other path appears, STOP.

---

## PR 4 — Standalones: dispatching-parallel-agents, systematic-debugging

**blockedBy:** nothing (both are standalone — zero cross-refs to vendored skills)

**Scope:** 8 files created. No hooks, no install.sh, no agentic-loop.

### Cruft to drop (systematic-debugging)

Do NOT copy:
- `CREATION-LOG.md` (superpowers-internal)
- `test-pressure-1.md`, `test-pressure-2.md`, `test-pressure-3.md` (superpowers-internal test fixtures)
- `test-academic.md` (superpowers-internal)

### Cross-references to rewrite (verified by grep)

**dispatching-parallel-agents/SKILL.md:** zero `superpowers:` refs (verified — grep returned no output). Copy as-is, then run scrub.

**systematic-debugging/SKILL.md:**
- Line 179: `superpowers:test-driven-development` → `coderails:test-driven-development`
- Line 287: `superpowers:test-driven-development` → `coderails:test-driven-development`
- Line 288: `superpowers:verification-before-completion` → `coderails:verification-before-completion`

**All other systematic-debugging files** (`condition-based-waiting-example.ts`, `condition-based-waiting.md`, `defense-in-depth.md`, `find-polluter.sh`, `root-cause-tracing.md`): zero `superpowers:` refs (verified — grep returned no output). Copy as-is, then run scrub per-file as a guard.

### Tasks

#### Task 4.1 — Copy and rebrand dispatching-parallel-agents

**Files to create:**
- `skills/dispatching-parallel-agents/SKILL.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/dispatching-parallel-agents/SKILL.md`

**Construction method:** inspection + scrub. Steps:

1. Copy the file.
2. Run scrub: `grep -rIi 'superpowers' skills/dispatching-parallel-agents/SKILL.md` — must return zero output (expected to pass immediately; grep returned no output on source, but verify after copy).
3. Verify frontmatter `name: dispatching-parallel-agents`.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/dispatching-parallel-agents/SKILL.md
# Expected: no output
grep '^name:' skills/dispatching-parallel-agents/SKILL.md
# Expected: name: dispatching-parallel-agents
```

---

#### Task 4.2 — Copy, rebrand, and drop cruft for systematic-debugging

**Files to create:**
- `skills/systematic-debugging/SKILL.md`
- `skills/systematic-debugging/condition-based-waiting-example.ts`
- `skills/systematic-debugging/condition-based-waiting.md`
- `skills/systematic-debugging/defense-in-depth.md`
- `skills/systematic-debugging/find-polluter.sh`
- `skills/systematic-debugging/root-cause-tracing.md`

**Files to NOT copy (cruft):** `CREATION-LOG.md`, `test-pressure-1.md`, `test-pressure-2.md`, `test-pressure-3.md`, `test-academic.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/systematic-debugging/`

**Construction method:** inspection + scrub. Steps:

1. Copy only the 6 files listed above (do not copy the 5 cruft files).
2. In `SKILL.md` apply three namespace rewrites (lines 179, 287, 288).
3. Run scrub: `grep -rIi 'superpowers' skills/systematic-debugging` — must return zero output.
4. Verify frontmatter `name: systematic-debugging`.
5. Confirm cruft files are absent: `ls skills/systematic-debugging/` must not contain `CREATION-LOG.md`, `test-pressure-*.md`, `test-academic.md`.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/systematic-debugging
# Expected: no output

ls skills/systematic-debugging/
# Expected: SKILL.md condition-based-waiting-example.ts condition-based-waiting.md
#           defense-in-depth.md find-polluter.sh root-cause-tracing.md
# Must NOT include: CREATION-LOG.md test-pressure-1.md test-pressure-2.md
#                   test-pressure-3.md test-academic.md

grep 'coderails:test-driven-development' skills/systematic-debugging/SKILL.md | wc -l
# Expected: 2 (lines 179 and 287)
grep 'coderails:verification-before-completion' skills/systematic-debugging/SKILL.md | wc -l
# Expected: 1 (line 288)
```

**Manifest (PR4 combined):** 7 new files. Zero existing files modified.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only files under `skills/dispatching-parallel-agents/` and `skills/systematic-debugging/`. If any other path appears, STOP.

---

## PR 5 — Overlaps: verification-before-completion, writing-skills

**blockedBy:** nothing (verification-before-completion has zero cross-refs; writing-skills refs `coderails:test-driven-development` which is already present)

**Scope:** 7 files created under `skills/verification-before-completion/` and `skills/writing-skills/`. No hooks, no install.sh, no agentic-loop.

### Cruft to drop (writing-skills)

Do NOT copy:
- `examples/CLAUDE_MD_TESTING.md` (superpowers-internal authoring fixture)
- The `examples/` directory is dropped entirely (contains only `CLAUDE_MD_TESTING.md`)

### Cross-references to rewrite (verified by grep)

**verification-before-completion/SKILL.md:** zero `superpowers:` refs (verified). Copy as-is, then run scrub.

**writing-skills/SKILL.md** — 6 `superpowers:` occurrences:
- Line 12: `../using-superpowers/references/claude-code-tools.md`, `codex-tools.md`, `copilot-tools.md`, `gemini-tools.md` → `../using-coderails/references/claude-code-tools.md`, etc. (all four paths in the sentence updated)
- Line 18: `superpowers:test-driven-development` → `coderails:test-driven-development`
- Line 283: `superpowers:test-driven-development` → `coderails:test-driven-development`
- Line 284: `superpowers:systematic-debugging` → `coderails:systematic-debugging`
- Line 393: `superpowers:test-driven-development` → `coderails:test-driven-development`

**writing-skills/testing-skills-with-subagents.md** — line 13 (illustrative, non-functional):
- `superpowers:test-driven-development` → `coderails:test-driven-development` (keep the file; rebrand the illustrative ref so the scrub passes; note in commit message that this is an illustrative example, not a live skill call)

**All other writing-skills files** (`anthropic-best-practices.md`, `graphviz-conventions.dot`, `persuasion-principles.md`, `render-graphs.js`): inspect each for `superpowers` refs before copying; expected zero based on file content (no grep output on source tree), but verify post-copy.

### Tasks

#### Task 5.1 — Copy and rebrand verification-before-completion

**Files to create:**
- `skills/verification-before-completion/SKILL.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/verification-before-completion/SKILL.md`

**Construction method:** inspection + scrub. Steps:

1. Copy the file.
2. Run scrub: `grep -rIi 'superpowers' skills/verification-before-completion` — must return zero output.
3. Verify frontmatter `name: verification-before-completion`.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/verification-before-completion/SKILL.md
# Expected: no output
grep '^name:' skills/verification-before-completion/SKILL.md
# Expected: name: verification-before-completion
```

---

#### Task 5.2 — Copy, rebrand, and drop cruft for writing-skills

**Files to create:**
- `skills/writing-skills/SKILL.md`
- `skills/writing-skills/testing-skills-with-subagents.md`
- `skills/writing-skills/anthropic-best-practices.md`
- `skills/writing-skills/graphviz-conventions.dot`
- `skills/writing-skills/persuasion-principles.md`
- `skills/writing-skills/render-graphs.js`

**Files to NOT copy (cruft):** `examples/CLAUDE_MD_TESTING.md` (and the `examples/` dir entirely)

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/writing-skills/`

**Construction method:** inspection + scrub. Steps:

1. Copy the 6 files listed (do not copy the `examples/` directory).
2. In `SKILL.md` apply all 6 namespace and path rewrites (lines 12, 18, 283, 284, 393 — see cross-references above).
3. In `testing-skills-with-subagents.md` line 13: replace `superpowers:test-driven-development` with `coderails:test-driven-development`.
4. Inspect `anthropic-best-practices.md`, `graphviz-conventions.dot`, `persuasion-principles.md`, `render-graphs.js` for any `superpowers` occurrence — fix if found, expected zero.
5. Run scrub: `grep -rIi 'superpowers' skills/writing-skills` — must return zero output.
6. Verify frontmatter `name: writing-skills`.
7. Confirm `examples/` directory does not exist under `skills/writing-skills/`: `ls skills/writing-skills/` must not show `examples`.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/writing-skills
# Expected: no output

ls skills/writing-skills/
# Expected: SKILL.md testing-skills-with-subagents.md anthropic-best-practices.md
#           graphviz-conventions.dot persuasion-principles.md render-graphs.js
# Must NOT include: examples/

grep '../using-coderails/references/' skills/writing-skills/SKILL.md
# Expected: 1 match (line 12 rewritten path)

grep 'coderails:test-driven-development' skills/writing-skills/SKILL.md | wc -l
# Expected: 3 (lines 18, 283, 393)
grep 'coderails:systematic-debugging' skills/writing-skills/SKILL.md
# Expected: 1 match (line 284)
```

**Manifest (PR5 combined):** 7 new files. Zero existing files modified.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only files under `skills/verification-before-completion/` and `skills/writing-skills/`. If any other path appears, STOP.

---

## PR 6 — Bootstrap: using-coderails + inject_bootstrap.sh + SessionStart hook

**blockedBy:** nothing (using-coderails has zero cross-refs to other vendored skills; the bootstrap hook reads only `skills/using-coderails/SKILL.md`, which this same PR creates)

**Scope:** 9 new files + 2 modified files (`hooks/hooks.json`, `install.sh`).

### Cross-references to rewrite (using-superpowers source)

**using-superpowers/SKILL.md:** line 2 `name: using-superpowers` → `name: using-coderails`; all body references to "Superpowers" brand → "coderails". The using-superpowers SKILL.md has very few `superpowers:` namespace refs in its body (the file mostly discusses skill-invocation mechanics, not cross-skill deps). Full scrub required.

**using-superpowers/references/antigravity-tools.md:**
- Line 27: `.../plugins/superpowers/skills/<skill-name>/SKILL.md` → `.../plugins/coderails/skills/<skill-name>/SKILL.md`
- Line 61: `superpowers:subagent-driven-development` → `coderails:subagent-driven-development`

**using-superpowers/references/gemini-tools.md:**
- Line 34: `superpowers:subagent-driven-development` → `coderails:subagent-driven-development`
- Line 39: `superpowers:requesting-code-review` → `coderails:requesting-code-review`

**Other references files** (`claude-code-tools.md`, `codex-tools.md`, `copilot-tools.md`, `pi-tools.md`): inspect each for `superpowers` refs; expected low count based on pattern — fix any found.

### Bootstrap hook logic

`inject_bootstrap.sh` must emit the following JSON shape (Claude Code SessionStart hook format):

```json
{
  "hookSpecificOutput": {
    "additionalContext": "<EXTREMELY_IMPORTANT>\n{SKILL_MD_CONTENT_JSON_ESCAPED}\n</EXTREMELY_IMPORTANT>"
  }
}
```

Where `{SKILL_MD_CONTENT_JSON_ESCAPED}` is the content of `skills/using-coderails/SKILL.md`, JSON-escaped using bash-3.2-safe parameter substitution (no `python3 -c`, no `node -e` — only `${var//old/new}` chains for `\`, `"`, and newline handling). The branding text inside the wrapping tag must say "coderails" — not "superpowers".

The `EXTREMELY_IMPORTANT` block content must not contain the literal string "superpowers" (the body scrub in using-coderails/SKILL.md guarantees this upstream; the test confirms it end-to-end).

`inject_bootstrap.sh` must gracefully no-op (exit 0, emit `{}`) if `skills/using-coderails/SKILL.md` is missing.

The script locates the skill file via `${CLAUDE_PLUGIN_ROOT}/skills/using-coderails/SKILL.md` (same env var pattern as all other hooks).

### hooks.json SessionStart block shape

```json
"SessionStart": [
  {
    "matcher": "startup|clear|compact",
    "hooks": [
      {
        "type": "command",
        "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject_bootstrap.sh\"",
        "timeout": 5
      }
    ]
  }
]
```

This block is added as a new top-level key in `hooks.hooks` alongside the existing `UserPromptSubmit`, `Stop`, `PreToolUse` keys.

### install.sh chmod addition

After the existing last entry (`hooks/scripts/test_gate.sh`) in the `for script in` list (line 329), add:
```
hooks/scripts/inject_bootstrap.sh \
```

The full loop becomes: existing 12 scripts + `hooks/scripts/inject_bootstrap.sh`.

### Tasks

#### Task 6.1 — Write inject_bootstrap.test.sh (failing test first, TDD gate 1)

**File to create:**
- `hooks/scripts/tests/inject_bootstrap.test.sh`

**Construction method:** Use `coderails:test-driven-development`. Write the test **before** the implementation exists. Steps:

1. Create `hooks/scripts/tests/inject_bootstrap.test.sh`. The test script must:
   a. Create a temp dir and write a stub `skills/using-coderails/SKILL.md` containing "coderails bootstrap content" and a PLUGIN_ROOT env structure.
   b. Set `CLAUDE_PLUGIN_ROOT` to the temp dir structure, call `hooks/scripts/inject_bootstrap.sh`.
   c. Assert: output is valid JSON (`jq . >/dev/null` exits 0).
   d. Assert: output contains `hookSpecificOutput.additionalContext` (jq path check).
   e. Assert: `additionalContext` contains "coderails bootstrap content" (the SKILL.md body is embedded).
   f. Assert: `additionalContext` does NOT contain the literal string "superpowers".
   g. Assert: when `SKILL.md` is missing (point CLAUDE_PLUGIN_ROOT at a dir without it), the script exits 0 and emits `{}` or valid empty JSON (no crash).
2. Run: `bash hooks/scripts/tests/inject_bootstrap.test.sh` → must fail (script does not exist yet). Confirm the failure is "no such file" or "command not found" — not a logic error.

**Interfaces produced:**
- Test entry point: `bash hooks/scripts/tests/inject_bootstrap.test.sh` — exits 0 on pass, non-zero on fail, writes pass/fail messages to stdout.

**Verify criteria:**
```
bash hooks/scripts/tests/inject_bootstrap.test.sh
# Expected: non-zero exit (script under test does not exist yet)
# Failure message must be about missing inject_bootstrap.sh, not about the test itself
```

---

#### Task 6.2 — Implement inject_bootstrap.sh (TDD gate 2: make tests pass)

**File to create:**
- `hooks/scripts/inject_bootstrap.sh`

**Construction method:** write minimal implementation to pass Task 6.1's test. Steps:

1. Create `hooks/scripts/inject_bootstrap.sh`:

```bash
#!/usr/bin/env bash
# SessionStart hook — injects using-coderails SKILL.md as additionalContext.
# Bash-3.2-safe (macOS): uses only ${var//old/new} for JSON escaping.

SKILL_FILE="${CLAUDE_PLUGIN_ROOT}/skills/using-coderails/SKILL.md"

if [[ ! -f "$SKILL_FILE" ]]; then
  echo '{}'
  exit 0
fi

s=$(cat "$SKILL_FILE")

# JSON-escape: backslash first, then double-quote, then newline.
s="${s//\\/\\\\}"
s="${s//\"/\\\"}"
s="${s//$'\n'/\\n}"

printf '{"hookSpecificOutput":{"additionalContext":"<EXTREMELY_IMPORTANT>\\n%s\\n</EXTREMELY_IMPORTANT>"}}\n' "$s"
```

2. `chmod +x hooks/scripts/inject_bootstrap.sh`.
3. Run: `bash hooks/scripts/tests/inject_bootstrap.test.sh` → must pass (all assertions green).
4. If any assertion fails, fix the implementation (not the test) and re-run. Do not modify the test to match a broken implementation.

**Verify criteria:**
```
bash hooks/scripts/tests/inject_bootstrap.test.sh
# Expected: exit 0, all assertions printed as PASS

# Spot-check bash-3.2 safety (no bashisms beyond 3.2):
bash --version   # note the version; the script must not use features from bash 4+
# Critical: the ${var//old/new} substitution is 3.2-safe; $'\n' is 3.2-safe.
# bash 4+ features to avoid: associative arrays, [[ -v var ]], readarray, mapfile.
```

---

#### Task 6.3 — Copy and rebrand using-coderails skill

**Files to create:**
- `skills/using-coderails/SKILL.md`
- `skills/using-coderails/references/antigravity-tools.md`
- `skills/using-coderails/references/claude-code-tools.md`
- `skills/using-coderails/references/codex-tools.md`
- `skills/using-coderails/references/copilot-tools.md`
- `skills/using-coderails/references/gemini-tools.md`
- `skills/using-coderails/references/pi-tools.md`

**Source:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.0.3/skills/using-superpowers/`

**Construction method:** inspection + scrub. Steps:

1. Copy `SKILL.md` and the entire `references/` directory (6 files) into `skills/using-coderails/`.
2. In `SKILL.md`: change `name: using-superpowers` → `name: using-coderails`; replace all "Superpowers" brand references in the body with "coderails"; replace `superpowers:` namespace prefix → `coderails:` wherever it appears.
3. In `references/antigravity-tools.md`: apply line 27 and line 61 rewrites (see above).
4. In `references/gemini-tools.md`: apply line 34 and line 39 rewrites.
5. Inspect `claude-code-tools.md`, `codex-tools.md`, `copilot-tools.md`, `pi-tools.md`: fix any `superpowers` occurrence found.
6. Run scrub: `grep -rIi 'superpowers' skills/using-coderails` — must return zero output.
7. Verify frontmatter `name: using-coderails`.

**Critical:** this file is what `inject_bootstrap.sh` reads at runtime. The scrub passing here guarantees the bootstrap will not inject "superpowers" into the context.

**Verify criteria:**
```
grep -rIi 'superpowers' skills/using-coderails
# Expected: no output

grep '^name:' skills/using-coderails/SKILL.md
# Expected: name: using-coderails

# Re-run bootstrap test with real SKILL.md in place:
CLAUDE_PLUGIN_ROOT="$(pwd)" bash hooks/scripts/tests/inject_bootstrap.test.sh
# Expected: exit 0, all assertions pass

# Confirm the inject script runs against the real file:
CLAUDE_PLUGIN_ROOT="$(pwd)" bash hooks/scripts/inject_bootstrap.sh | jq '.hookSpecificOutput.additionalContext' | grep -c 'coderails'
# Expected: >= 1 (the SKILL.md content mentions coderails at least once)
```

---

#### Task 6.4 — Add SessionStart block to hooks.json and chmod entry to install.sh

**Files to modify:**
- `hooks/hooks.json`
- `install.sh`

**Construction method:** inspection (JSON edit + shell script edit — no testable logic). Steps:

1. In `hooks/hooks.json`: add the `"SessionStart"` key to the `"hooks"` object with the exact block shown in the spec section above. The result is a JSON object with four top-level keys under `"hooks"`: `UserPromptSubmit`, `Stop`, `PreToolUse`, `SessionStart`.
2. Validate JSON: `jq . hooks/hooks.json > /dev/null` must exit 0.
3. In `install.sh`: in the `for script in` loop (lines 322-329), add `hooks/scripts/inject_bootstrap.sh \` after `hooks/scripts/test_gate.sh`. The backslash on `test_gate.sh` line changes from nothing to `\` if it's the last item; ensure the loop terminates correctly (the last item in the list has no trailing backslash, or the loop uses `;` — match the existing style).
4. Verify: `bash install.sh --dry-run` shows `chmod +x .../hooks/scripts/inject_bootstrap.sh` in its output.

**Verify criteria:**
```
jq . hooks/hooks.json > /dev/null && echo "valid JSON"
# Expected: valid JSON

jq '.hooks | keys' hooks/hooks.json
# Expected: ["PreToolUse","SessionStart","Stop","UserPromptSubmit"] (or similar order)

jq '.hooks.SessionStart[0].hooks[0].command' hooks/hooks.json
# Expected: "\"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject_bootstrap.sh\""

bash install.sh --dry-run 2>&1 | grep inject_bootstrap
# Expected: one line showing chmod for inject_bootstrap.sh
```

**Manifest (PR6 combined):**
- 9 new files: `skills/using-coderails/SKILL.md`, `skills/using-coderails/references/{antigravity,claude-code,codex,copilot,gemini,pi}-tools.md`, `hooks/scripts/tests/inject_bootstrap.test.sh`, `hooks/scripts/inject_bootstrap.sh`
- 2 modified files: `hooks/hooks.json`, `install.sh`

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only files under `skills/using-coderails/`, `hooks/scripts/tests/inject_bootstrap.test.sh`, `hooks/scripts/inject_bootstrap.sh`, `hooks/hooks.json`, `install.sh`. If any other path appears, STOP.

---

## PR 7 — Phase 2 Rewire: agentic-loop stale-ref fix + SDD reference addition

**blockedBy:** PR2 (`coderails:subagent-driven-development` must exist before the reference is added and meaningful to a reviewer)

**Scope:** 1 file modified: `skills/agentic-loop/SKILL.md`. Three edits total. C1/C2 no-touch regions stay byte-identical.

### Exact edits (line-referenced)

**Edit 1 — stale ref, line 13:**

Current text (substring):
```
Running skills (`/planning-sequence`, `/premortem`, `/claude-guardrails:*`) in main context
```
Replace `claude-guardrails:*` with `coderails:assumptions`, `coderails:notchecked`:
```
Running skills (`/planning-sequence`, `/premortem`, `/coderails:assumptions`, `/coderails:notchecked`) in main context
```

**Edit 2 — stale ref, line 134:**

Current text (substring):
```
Pre-planning skills (`/planning-sequence`, `/premortem`, `/claude-guardrails:assumptions`, `/claude-guardrails:notchecked`, `/wiki-query`) belong in a delegated agent
```
Replace `claude-guardrails:assumptions` → `coderails:assumptions`, `claude-guardrails:notchecked` → `coderails:notchecked`:
```
Pre-planning skills (`/planning-sequence`, `/premortem`, `/coderails:assumptions`, `/coderails:notchecked`, `/wiki-query`) belong in a delegated agent
```

**Edit 3 — SDD reference addition, after line 239 (the TDD construction-method bullet in Phase 3 worker description):**

Current bullet (line 239):
```
- Construction method — when the deliverable is code (the change adds or alters a function, method, or branch that *can* carry a test), instruct the worker to build it test-first via `coderails:test-driven-development` (failing test → minimal code → refactor). This holds even if the unit also touches non-code files. For pure docs/config/prose with no testable code, there is no test to write first — keep the verify-your-artifact contract.
```

Add a new bullet immediately after (between the construction-method bullet and the verify-criteria bullet):
```
- Worker-prompt construction contract — when the task will spawn a subagent that needs an implementer or reviewer prompt template, follow `coderails:subagent-driven-development`'s prompt-construction contract: the implementer prompt is the task description fully self-contained (worktree path, branch, steps, manifest, terminal state); the reviewer prompt uses `../requesting-code-review/code-reviewer.md` as its template. The same-session vs parallel-session distinction (SDD vs executing-plans) is resolved at Phase 2.8 plan time, not per-worker at Phase 3.
```

This is additive — no existing bullet is removed.

### C1/C2 no-touch region verification

Before and after the three edits, confirm these six regions are byte-identical to their state on `origin/main`:

1. **Frontmatter `description:`** — the `description:` line in the YAML frontmatter.
2. **Phase -2** — the section starting with `### Phase -2`.
3. **Phase 0.5 LOOP-STOP bullet** — the bullet containing `LOOP-STOP` in Phase 0.5.
4. **Phase 13 KPI bullet** — the KPI bullet in Phase 13.
5. **Stop-conditions LOOP-STOP block** — the Stop-conditions section containing `LOOP-STOP`.
6. **Context-window-persistence lifecycle section** — the lifecycle section.

Verification command (run before push):
```bash
git diff origin/main skills/agentic-loop/SKILL.md | grep '^[-+]' | grep -v '^---\|^+++' | wc -l
# Expected: exactly 3 changed lines (2 stale-ref fixes + 1 new bullet = 3 net additions, 2 net removals = 5 diff lines total)
# If count is higher, a no-touch region was accidentally modified — STOP.
```

### Tasks

#### Task 7.1 — Apply three edits to agentic-loop/SKILL.md

**File to modify:** `skills/agentic-loop/SKILL.md`

**Construction method:** inspection (prose edits — no testable logic). Steps:

1. Read `skills/agentic-loop/SKILL.md` line 13 and confirm the current text matches `claude-guardrails:*`. Apply Edit 1.
2. Read line 134 and confirm the current text matches `claude-guardrails:assumptions` and `claude-guardrails:notchecked`. Apply Edit 2.
3. Read line 239 (construction-method bullet). Insert the new worker-prompt-construction bullet immediately after. Apply Edit 3.
4. Run the byte-diff check: `git diff origin/main skills/agentic-loop/SKILL.md`. Inspect: only the three targeted lines change. If any change appears in a no-touch region (frontmatter description, Phase -2, Phase 0.5, Phase 13 KPI, Stop-conditions, Context-window-persistence), STOP and revert.
5. Run the existing hook test suites:
   ```
   bash hooks/scripts/tests/loop_state_guard.test.sh
   bash hooks/scripts/tests/loop_stall_guard.test.sh
   bash hooks/scripts/tests/agentic_loop_path.test.sh
   ```
   All must exit 0 (these tests do not parse SKILL.md content, but they confirm the hook infrastructure is intact post-edit).

**Verify criteria:**
```
# Stale-ref fix confirmed:
grep 'claude-guardrails' skills/agentic-loop/SKILL.md
# Expected: no output (both occurrences replaced)

grep 'coderails:assumptions' skills/agentic-loop/SKILL.md | wc -l
# Expected: 2 (lines 13 and 134)
grep 'coderails:notchecked' skills/agentic-loop/SKILL.md | wc -l
# Expected: 2 (lines 13 and 134)

# SDD reference added:
grep 'coderails:subagent-driven-development' skills/agentic-loop/SKILL.md
# Expected: 1 match (the new Phase 3 bullet)

# No-touch regions untouched (byte-diff check):
git diff origin/main skills/agentic-loop/SKILL.md | grep '^[-+]' | grep -v '^---\|^+++' | wc -l
# Expected: 5 or fewer (2 stale-ref replacements = 4 lines changed + 1 addition = 5 diff lines)
# If higher, a no-touch region was modified — abort.

# Hook suites:
bash hooks/scripts/tests/loop_state_guard.test.sh   # → exit 0
bash hooks/scripts/tests/loop_stall_guard.test.sh   # → exit 0
bash hooks/scripts/tests/agentic_loop_path.test.sh  # → exit 0
```

**Manifest:** 1 modified file: `skills/agentic-loop/SKILL.md`.

**Pre-push scope assertion:** `git diff origin/main --name-only` must show only `skills/agentic-loop/SKILL.md`. If any other path appears, STOP.

---

## Self-Review Gate

### Spec coverage check

| Spec requirement | Plan task |
|---|---|
| Vendor using-git-worktrees | PR1 Task 1.1 |
| Vendor requesting-code-review (+code-reviewer.md) | PR1 Task 1.1 |
| Vendor receiving-code-review | PR1 Task 1.1 |
| Vendor finishing-a-development-branch | PR1 Task 1.1 |
| Vendor subagent-driven-development (+scripts) | PR2 Task 2.1 |
| Vendor executing-plans (semantic rewrite line 14) | PR2 Task 2.2 |
| Vendor brainstorming (+visual companion + Decision Ledger) | PR3 Tasks 3.1, 3.2 |
| Vendor dispatching-parallel-agents | PR4 Task 4.1 |
| Vendor systematic-debugging (keep content companions; drop cruft) | PR4 Task 4.2 |
| Vendor verification-before-completion | PR5 Task 5.1 |
| Vendor writing-skills (keep testing-skills-with-subagents; drop examples cruft) | PR5 Task 5.2 |
| Vendor using-coderails (+references/) | PR6 Task 6.3 |
| inject_bootstrap.sh (TDD) + SessionStart hooks.json block | PR6 Tasks 6.1, 6.2, 6.4 |
| install.sh chmod entry | PR6 Task 6.4 |
| uninstall.sh symmetry | Addressed in PR6 notes (no script-specific reversal needed; chmod not reversed by uninstall; hook removed by /plugin uninstall) |
| Phase 2 additive rewire: SDD reference in Phase 3 | PR7 Task 7.1 |
| Phase 2 stale-ref cleanup: claude-guardrails → coderails | PR7 Task 7.1 |
| C1/C2 no-touch regions byte-identical | PR7 Task 7.1 verify criteria |
| Rebrand scrub: no superpowers string in any shipped file | Every PR verify criteria |

### Placeholder scan

No "TBD", "TODO", or "implement later" phrases present. All code steps show the exact command or code. All cross-references list exact line numbers (verified by grep during plan construction).

### Type/name consistency

- The SDD reference in PR7 uses `coderails:subagent-driven-development` — consistent with PR2's frontmatter `name: subagent-driven-development`.
- The bootstrap inject reads `skills/using-coderails/SKILL.md` — consistent with PR6 Task 6.3's destination path.
- The `references/` relative path `../using-coderails/references/` in writing-skills (PR5) resolves correctly once PR6 creates `skills/using-coderails/references/` — the two PRs are in the correct independent order (PR5 and PR6 are independent; writing-skills is usable before using-coderails exists because the ref is navigational, not functional).
