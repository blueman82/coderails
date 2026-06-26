**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Engineering-Principles Vendoring Implementation Plan

**Goal:** Vendor the global `strictcode` skill family into coderails as `engineering-principles`, leaving no `strictcode`/`scout`/`slimcode` traces, and wire it into three workflow touchpoints (plan/push/review) plus `/simplify` at review.

**Architecture:** Four skills are copied from `~/.claude/skills/strictcode*` into `skills/engineering-principles*` and transformed (rename + Scout/SlimCode strip + Grep fallback). The config keys `strictcode_paths`/`strictcode_skill` are renamed to `engineering_principles_paths`/`engineering_principles_skill` across the four command files and the repo's own config. Planning skills (`writing-plans`, `brainstorming`) gain a principle-vetting touchpoint; `workflow.md`'s Phase 3 gains a verify + `/simplify` step. Docs are synced. Global copies are removed post-merge.

## Global Constraints
- No new hook — engineering-principles stays a skill invoked by commands (commands = advisory, hooks = mechanical, per CLAUDE.md).
- After transform, skill bodies + command files + docs contain **zero** `strictcode`, `scout-`, or `slimcode` strings.
- Keep Serena (`mcp__mcp-exec__*`) usage and its graceful-degradation clause intact.
- All edits to `skills/*/SKILL.md` and `commands/*.md` are blocked on `main` by `no_edit_on_main` — work on a feature branch (Task 0).
- Markdown/prose tasks verify by inspection (grep), not TDD — there is no testable code in this plan except the untouched hook suite (Task 11).

## Canonical token map (used by every rename task)
```
strictcode-python   → engineering-principles-python
strictcode-go       → engineering-principles-go
strictcode-ts       → engineering-principles-ts
/strictcode (coordinator command)   → /engineering-principles
strictcode_paths    → engineering_principles_paths
strictcode_skill    → engineering_principles_skill
"strictcode pre-flight" / prose     → "engineering-principles pre-flight"
default value /strictcode-python     → /engineering-principles-python
```

---

## Task 0 — Feature branch

**Files:** none (git only)

**Steps:**
- [ ] Run `/coderails:prep feature/engineering-principles "Vendor strictcode as engineering-principles"` (or `git worktree add` per repo convention) to get an isolated branch off `main`.

**Verify:**
- [ ] `git rev-parse --abbrev-ref HEAD` prints `feature/engineering-principles` (not `main`).

---

## Task 1 — Vendor + transform the coordinator skill

**Files:**
- Create `skills/engineering-principles/SKILL.md` (source: `~/.claude/skills/strictcode/SKILL.md`)

**Consumes:** the token map above.
**Produces:** skill `engineering-principles`, whose Phase 0 dispatch table routes `.go → engineering-principles-go`, `.py → engineering-principles-python`, `.ts/.tsx → engineering-principles-ts` (consumed by Task 2's existence; referenced by Tasks 3/4/6 defaults).

**Steps:**
- [ ] Copy `~/.claude/skills/strictcode/SKILL.md` to `skills/engineering-principles/SKILL.md`.
- [ ] Frontmatter: set `name: engineering-principles`. In `description:`, replace `explicit /strictcode command` with `explicit /engineering-principles command`. Keep the Serena sentence and `allowed-tools: Read, Write, Edit, Glob, Grep, Skill, mcp__mcp-exec__*`.
- [ ] Title/body: `# StrictCode - ...` → `# Engineering Principles - Engineering Principles & Language Standards`; bump `**Version:**` to `4.0.0`; `**Purpose:**` keep wording but drop nothing about Serena.
- [ ] Phase 0 + Step 1 dispatch tables: change the three `strictcode-*` skill names to `engineering-principles-*`.
- [ ] **Delete Phase 3 (Semantic Analysis via Scout)** entirely — the whole `## Phase 3 ...` section through just before `## Core Principles`.
- [ ] **Delete the `## Integration with SlimCode` section** entirely (the final section).
- [ ] Replace the Core Principles table rows so cross-file tools become Grep/Glob:
  ```
  | 1 | **YAGNI** | Unused code, speculative features, dead branches | Serena `find_referencing_symbols` (LSP-precise); else Grep for call sites |
  | 2 | **KISS** | Over-engineered abstractions, trivial classes | Serena `find_symbol` depth → single-method classes |
  | 3 | **DRY** | Duplicated logic across files | Grep/Glob for repeated signatures or body fragments across files |
  | 4 | **Fail Fast** | Late validation, deep nesting before error checks | Serena `find_symbol` body → nesting depth |
  | 5 | **SSOT** | Duplicated state/config | Grep for the same config key/value in 2+ files |
  | 6 | **Law of Demeter** | `a.b.c.d` chains | Serena `find_symbol` body → chain regex |
  ```
- [ ] Replace the `**Tool selection rule:**` line under that table with:
  `**Tool selection rule:** Serena for in-file structural analysis (LSP-backed, authoritative) when available; plain Grep/Glob for cross-file checks and as the fallback when Serena is absent.`
- [ ] Replace the Step 2 block with:
  ```
  ### Step 2: Analyze
  - **If Serena available:** Run symbol overview, reference counting, depth analysis (Phase 2)
  - **Cross-file analysis:** Grep/Glob for duplicated signatures (DRY), repeated config keys (SSOT), call sites (YAGNI)
  - **If Serena unavailable:** Fall back entirely to file-level static analysis via Read/Grep/Glob
  ```
- [ ] In the `## Rules` list, replace the `Use scout skills ...` bullet with `Use Grep/Glob for cross-file checks (DRY/SSOT/YAGNI)`, and soften `Trust LSP data (Serena) over heuristics for in-file analysis` → append ` when available`.

**Verify:**
- [ ] `grep -niE 'scout|slimcode' skills/engineering-principles/SKILL.md` → no matches.
- [ ] `grep -niE 'strictcode' skills/engineering-principles/SKILL.md` → no matches.
- [ ] `grep -n 'engineering-principles-' skills/engineering-principles/SKILL.md` → shows the three dispatch targets.
- [ ] `grep -c 'serena' skills/engineering-principles/SKILL.md` → still > 0 (Serena retained).

---

## Task 2 — Vendor + rename the three language sub-skills

**Files:**
- Create `skills/engineering-principles-python/SKILL.md` (source: `~/.claude/skills/strictcode-python/SKILL.md`)
- Create `skills/engineering-principles-go/SKILL.md` (source: `~/.claude/skills/strictcode-go/SKILL.md`)
- Create `skills/engineering-principles-ts/SKILL.md` (source: `~/.claude/skills/strictcode-ts/SKILL.md`)

**Consumes:** dispatch-target names produced by Task 1.

**Steps:**
- [ ] Copy each source file to its `engineering-principles-*` path.
- [ ] In each, set `name:` frontmatter to the matching `engineering-principles-<lang>`.
- [ ] In each body, replace any self-reference token `strictcode-<lang>` → `engineering-principles-<lang>` and any `strictcode` coordinator mention → `engineering-principles`. (These sub-skills carry no scout/slimcode refs — confirmed: only `mcp__mcp-exec__*` in `allowed-tools`.)

**Verify:**
- [ ] `grep -rniE 'strictcode|scout|slimcode' skills/engineering-principles-python skills/engineering-principles-go skills/engineering-principles-ts` → no matches.
- [ ] `grep -h '^name:' skills/engineering-principles-*/SKILL.md` → prints the three renamed names.

---

## Task 3 — Rename refs + config keys in `commands/push.md`

**Files:** `commands/push.md` (pre-flight section, lines ~11-34)

**Consumes:** token map. **Produces:** `config.engineering_principles_paths` / `config.engineering_principles_skill` read semantics, default `/engineering-principles-python` (referenced identically by Tasks 4/6).

**Steps:**
- [ ] In the "Pre-flight: strictcode check" heading and body, apply the token map: `strictcode_paths`→`engineering_principles_paths`, `strictcode_skill`→`engineering_principles_skill`, default `/strictcode-python`→`/engineering-principles-python`, and the heading "strictcode check"→"engineering-principles check".

**Verify:**
- [ ] `grep -niE 'strictcode' commands/push.md` → no matches.
- [ ] `grep -n 'engineering_principles_paths\|engineering-principles-python' commands/push.md` → matches present.

---

## Task 4 — Rename + add review-phase steps in `commands/workflow.md`

**Files:** `commands/workflow.md` (frontmatter line 2; lines 14, 30, 139-141; Phase 3 lines 143-155)

**Consumes:** `/engineering-principles*` skill names (Tasks 1-2); default `/engineering-principles-python` (Task 3).

**Steps:**
- [ ] Frontmatter `allowed-tools`: replace `SlashCommand(/strictcode-python), SlashCommand(/strictcode-go), SlashCommand(/strictcode-ts)` with `SlashCommand(/engineering-principles), SlashCommand(/engineering-principles-python), SlashCommand(/engineering-principles-go), SlashCommand(/engineering-principles-ts), SlashCommand(/simplify)`.
- [ ] Apply the token map to lines 14, 30, and 139-141 (config keys, default skill, the words "Strictcode pre-flight"→"Engineering-principles pre-flight").
- [ ] In **Phase 3**, insert a new step between current step 2 (`/pr-review-toolkit:review-pr all`) and the "Apply worthwhile findings" step:
  ```
  2b. **Verify engineering principles** — run `/engineering-principles` on the cumulative diff against the base branch. Treat its output by the same rule as `/push`'s pre-flight: deviations from documented architectural conventions are blocking; style notes are non-blocking.
  2c. **Simplify** — run `/simplify` on the diff (built-in command). `review-pr`'s own `code-simplifier` agent only runs "after passing review" and is not guaranteed, so this is the explicit simplify pass.
  ```
  Renumber so findings from 2b/2c feed the same "apply worthwhile findings inline" loop (current step 3).

**Verify:**
- [ ] `grep -niE 'strictcode' commands/workflow.md` → no matches.
- [ ] `grep -n '/engineering-principles\b\|/simplify' commands/workflow.md` → matches in frontmatter and Phase 3.
- [ ] `grep -n 'engineering_principles_paths' commands/workflow.md` → matches at the former lines 14/30/139.

---

## Task 5 — Rename refs + config key in `commands/prep.md`

**Files:** `commands/prep.md` (line ~16)

**Steps:**
- [ ] Apply token map: `config.strictcode_paths = null → skip strictcode pre-flight` → `config.engineering_principles_paths = null → skip engineering-principles pre-flight`.

**Verify:**
- [ ] `grep -niE 'strictcode' commands/prep.md` → no matches.

---

## Task 6 — Rename scaffolder in `commands/init.md`

**Files:** `commands/init.md` (prompt block lines ~34-35; yaml template lines ~58-61)

**Consumes:** default skill name `/engineering-principles-python` and autodetect mapping.

**Steps:**
- [ ] Prompt line 34: `**Strictcode paths**` → `**Engineering-principles paths**` (keep the glob examples).
- [ ] Prompt line 35: `**Strictcode skill**` → `**Engineering-principles skill**`; rewrite the autodetect defaults to `go.mod → /engineering-principles-go`, `package.json` with `.ts` → `/engineering-principles-ts`, otherwise `/engineering-principles-python`; update the example list to the renamed skills.
- [ ] YAML template lines 58-61: `strictcode_paths` → `engineering_principles_paths`; `strictcode_skill: "/strictcode-python"` → `engineering_principles_skill: "/engineering-principles-python"`; update the inline comment listing `/strictcode-go, /strictcode-ts` → `/engineering-principles-go, /engineering-principles-ts`.

**Verify:**
- [ ] `grep -niE 'strictcode' commands/init.md` → no matches.
- [ ] `grep -n 'engineering_principles_skill\|engineering-principles-go\|engineering-principles-ts' commands/init.md` → matches present.

---

## Task 7 — Rename key in repo's own config

**Files:** `.claude/workflow.config.yaml`

**Steps:**
- [ ] Change `strictcode_paths: null` → `engineering_principles_paths: null`.

**Verify:**
- [ ] `grep -n 'engineering_principles_paths: null' .claude/workflow.config.yaml` → 1 match; `grep -c strictcode .claude/workflow.config.yaml` → 0.

---

## Task 8 — Planning touchpoint: `writing-plans`

**Files:** `skills/writing-plans/SKILL.md` (`## DRY / YAGNI / no placeholders` section ~line 29; `## Self-review gate` numbered list ~lines 52-54)

**Steps:**
- [ ] In the `## Self-review gate` numbered list, add a new item:
  `4. **Engineering principles**: each task's design honours YAGNI/KISS/DRY/Fail-Fast/SSOT/Law of Demeter — no speculative abstraction, no duplicated logic, fail-fast validation. See \`/engineering-principles\` for the full rubric; bake the constraints into tasks now rather than refactoring after review.`

**Verify:**
- [ ] `grep -n 'engineering-principles' skills/writing-plans/SKILL.md` → 1 match in the self-review gate.

---

## Task 9 — Planning touchpoint: `brainstorming`

**Files:** `skills/brainstorming/SKILL.md` (`**Design for isolation and clarity:**` ~line 89, or `## Key Principles` ~line 132)

**Steps:**
- [ ] After the `**Design for isolation and clarity:**` block, add a short bullet group framing the six principles as design constraints during exploration:
  `**Design against engineering principles:** as the design takes shape, pressure-test it against YAGNI (cut speculative features), KISS (no over-engineered abstractions), DRY/SSOT (one source of truth), Fail-Fast, and Law of Demeter. These are cheapest to honour now, in the design, not after code review. The \`/engineering-principles\` skill is the rubric.`

**Verify:**
- [ ] `grep -n 'engineering-principles' skills/brainstorming/SKILL.md` → 1 match.

---

## Task 10 — Docs sync

**Files:** `docs/REFERENCE.md` (lines ~288, 308, 330), `README.md` (skills table + count line 47). `CLAUDE.md` — confirmed **no** `strictcode` references (grep) and no per-skill inventory; expected no-op, verify only.

**Steps:**
- [ ] `docs/REFERENCE.md`: apply token map at lines 288/308/330 (push pre-flight wording, NO_CONFIG degradation paragraph, config table row). Where the config table names the field, use `engineering_principles_*`.
- [ ] `README.md`: add the four-skill `engineering-principles` family to the skills table (it carries no `strictcode` text today — this is an addition, not a rename); update the bundled-skill count `23 skills` → `27 skills` (line 47).
- [ ] `CLAUDE.md`: verify it still contains zero `strictcode` and decide if the new family warrants a one-line mention; expected no change.

**Verify:**
- [ ] `grep -rniE 'strictcode' docs/REFERENCE.md README.md` → no matches.
- [ ] `grep -n '27 skills' README.md` → 1 match.
- [ ] `grep -c 'strictcode' CLAUDE.md` → 0 (unchanged).

---

## Task 11 — Final verification sweep

**Files:** none (verification only)

**Steps:**
- [ ] `grep -rniE 'strictcode|scout-|slimcode' skills/engineering-principles* commands/ docs/REFERENCE.md CLAUDE.md README.md .claude/workflow.config.yaml` → expect **no matches**.
- [ ] `bash hooks/scripts/tests/run_all.sh` → expect the existing suite to pass unchanged (no hook logic was touched).
- [ ] `git grep -nE 'strictcode' -- ':!docs/coderails-engineering-principles-*'` → no matches outside the design/plan docs (which intentionally narrate the old name).

**Verify:**
- [ ] All three greps return as expected; hook suite green.

---

## Task 12 — Remove global copies (POST-MERGE, outside repo)

**Files:** `~/.claude/skills/strictcode`, `~/.claude/skills/strictcode-python`, `~/.claude/skills/strictcode-go`, `~/.claude/skills/strictcode-ts`

**Precondition:** PR merged AND Task 11 verification green AND the vendored `/engineering-principles` confirmed loadable in a fresh session.

**Steps:**
- [ ] `rm -rf ~/.claude/skills/strictcode ~/.claude/skills/strictcode-python ~/.claude/skills/strictcode-go ~/.claude/skills/strictcode-ts`

**Verify:**
- [ ] `ls ~/.claude/skills | grep -c strictcode` → 0.
- [ ] A fresh session can invoke `/engineering-principles` (the vendored copy) with no global fallback present.

---

## Self-review gate (plan vs spec)

1. **Spec coverage** — every spec §5 file maps to a task: coordinator (T1), 3 sub-skills (T2), push.md (T3), workflow.md incl. review phase (T4), prep.md (T5), init.md (T6), own config (T7), writing-plans (T8), brainstorming (T9), REFERENCE/CLAUDE/README (T10), global cleanup (T12). Scout-strip + Grep fallback (spec §4.1) = T1. `/simplify` include (spec decision 8) = T4 step 2c. No gaps.
2. **Placeholder scan** — no TBD/TODO; new-content blocks (T1 table, T4 2b/2c, T8/T9 inserts) are shown verbatim; rename tasks carry the canonical token map, not "similar to".
3. **Type/name consistency** — skill names `engineering-principles{,-python,-go,-ts}` and config keys `engineering_principles_{paths,skill}` are identical across T1–T10; default `/engineering-principles-python` consistent in T3/T4/T6.
