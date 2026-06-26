# Design: Vendor `engineering-principles` into coderails + 3-touchpoint wiring

**Date:** 2026-06-26
**Status:** Approved (design) — pending implementation plan
**Topic:** Bring the global `strictcode` skill family into coderails, rename it to
`engineering-principles`, and wire it into three workflow stages: planning,
pre-push, and PR review.

---

## 1. Problem / motivation

Today the `strictcode` skills (`strictcode`, `strictcode-python`, `strictcode-go`,
`strictcode-ts`) live in `~/.claude/skills/` — they are **global personal skills**,
not part of coderails. coderails only *references* them by name via
`config.strictcode_skill` (default `/strictcode-python`) as a **pre-push pre-flight**
in `push.md`/`workflow.md`.

Two problems:

1. **They're not self-contained.** coderails' direction is a self-contained plugin
   (the superpowers vendoring project). A core code-quality skill living outside the
   plugin breaks that.
2. **They only fire once, late.** The pre-flight runs at push. Engineering principles
   (YAGNI/KISS/DRY/Fail-Fast/SSOT/Law of Demeter) are cheapest to honour *at design
   time* — baking them into the plan avoids refactoring later — and they deserve an
   explicit *"were these followed?"* gate at review.

## 2. Goal

- Vendor the four skills into coderails, renamed to the `engineering-principles`
  family, with **no `strictcode` traces left behind** (names, config keys, skill
  bodies).
- Wire the renamed skill into **three touchpoints**: planning (advisory), pre-push
  (fix, existing), and PR review (verify) + `/simplify`.
- Keep coderails self-contained: strip references to tools coderails doesn't ship.

## 3. Decisions (locked with user)

| # | Decision | Choice |
|---|---|---|
| Scope | Vendor vs reference | **Vendor** all four skills into `skills/` |
| Naming | Coordinator + variants | **Rename whole family**: `engineering-principles`, `-python`, `-go`, `-ts` |
| Touchpoints | Where it runs | **Belt + braces**: plan (advisory) + push (fix, existing) + review (verify) |
| Plan hook | Which skills | **`writing-plans` + `brainstorming`** SKILL.md edits |
| Config keys | Rename vs keep | **Full rename** — `engineering_principles_paths` / `engineering_principles_skill`; no `strictcode_*` survives |
| External deps | scout/slimcode | **Keep Serena** (available, degrades gracefully); **strip scout Phase 3 + SlimCode section**; rewrite DRY/SSOT rows to Grep fallback |
| Global copies | After vendoring | **Remove** `~/.claude/skills/strictcode*` once vendored copies verified |
| `/simplify` | Include at review? | **Include** — `review-pr`'s `code-simplifier` agent is gated on "after passing review", not guaranteed; `/simplify` is the cheap insurance |

## 4. Design

### 4.1 Vendoring (4 new skill dirs)

Copy and transform `~/.claude/skills/strictcode{,-python,-go,-ts}` into:

```
skills/engineering-principles/SKILL.md          (name: engineering-principles)
skills/engineering-principles-python/SKILL.md   (name: engineering-principles-python)
skills/engineering-principles-go/SKILL.md       (name: engineering-principles-go)
skills/engineering-principles-ts/SKILL.md       (name: engineering-principles-ts)
```

Transformations applied to the **coordinator** body:
- `name:` frontmatter → `engineering-principles`; description keeps the six-principle
  summary, drops `/strictcode` trigger phrasing in favour of `/engineering-principles`.
- **Dispatch table** (Phase 0 + Step 1): `.go → engineering-principles-go`,
  `.py → engineering-principles-python`, `.ts/.tsx → engineering-principles-ts`.
- **Strip Phase 3 (Scout)** and the **"Integration with SlimCode"** section.
- **Principle table** (the 6-row table): rewrite the DRY and SSOT rows from
  `scout-search` to a **Grep/Glob** fallback; YAGNI keeps Serena
  `find_referencing_symbols` (drop the `scout-dead-code` alternative).
- **Keep Serena** (Phase 1–2) verbatim, including its existing graceful-degradation
  clause. Serena is reached via `mcp__mcp-exec__*` and is available in this env.

Transformations to the **language sub-skills**: only `name:` frontmatter rename and
any internal `strictcode` self-references; they already have no scout/slimcode deps
(verified — only `mcp__mcp-exec__*` in `allowed-tools`).

### 4.2 Three touchpoints

| Stage | File(s) | Change | Behaviour |
|---|---|---|---|
| **PLAN** | `skills/writing-plans/SKILL.md`, `skills/brainstorming/SKILL.md` | Add a step: vet the design against the six principles before tasks are written; cite `/engineering-principles`. No code exists yet → **advisory**, not a skill run. | Principles become design constraints |
| **PUSH** | `commands/push.md`, `commands/workflow.md` | Rename existing pre-flight refs `/strictcode-python` → `/engineering-principles-python`; config key rename. | Unchanged behaviour: **fixes** the diff before the PR opens |
| **REVIEW** | `commands/workflow.md` (review phase) | After `/pr-review-toolkit:review-pr`: run `/engineering-principles` on the diff (verify followed) **and** `/simplify` (built-in). | Explicit principles gate + guaranteed simplify pass |

### 4.3 Config key rename

`config.strictcode_paths` → `config.engineering_principles_paths`
`config.strictcode_skill` → `config.engineering_principles_skill` (default
`/engineering-principles-python`)

Read by four command files, the init scaffolder, and coderails' own config. The
default value and the `/init` autodetection map change with the family rename
(`go.mod → /engineering-principles-go`, `package.json`+`.ts → /engineering-principles-ts`,
else `/engineering-principles-python`).

## 5. File-by-file change list

**New (vendored):**
- `skills/engineering-principles/SKILL.md`
- `skills/engineering-principles-python/SKILL.md`
- `skills/engineering-principles-go/SKILL.md`
- `skills/engineering-principles-ts/SKILL.md`

**Renamed refs / config keys:**
- `commands/push.md` — pre-flight section, default skill, config keys
- `commands/workflow.md` — `allowed-tools` frontmatter (swap the three
  `SlashCommand(/strictcode-*)` for `/engineering-principles-*`; add
  `SlashCommand(/engineering-principles)` and `SlashCommand(/simplify)`); pre-flight;
  **add review-phase verify + simplify steps**
- `commands/prep.md` — `strictcode_paths` skip note + config key
- `commands/init.md` — scaffolder prompts, yaml template, autodetection defaults
- `.claude/workflow.config.yaml` — `strictcode_paths: null` → `engineering_principles_paths: null`

**Planning touchpoints:**
- `skills/writing-plans/SKILL.md` — principles-vetting step
- `skills/brainstorming/SKILL.md` — YAGNI/KISS/DRY design framing

**Docs:**
- `docs/REFERENCE.md` — command table (push pre-flight wording), config table,
  graceful-degradation line, NO_CONFIG paragraph
- `CLAUDE.md` — the "if you add a config field, update all four" note; skill
  inventory; any `strictcode` mentions
- `README.md` — skills table + bundled-skill count (23 → 27)

**Global cleanup (outside repo, after verification):**
- `rm -rf ~/.claude/skills/strictcode ~/.claude/skills/strictcode-{python,go,ts}`

## 6. Out of scope / non-goals

- No change to `/simplify` itself (built-in, every Claude Code user has it).
- No change to `pr-review-toolkit` (external plugin) — coderails wires around it.
- No new hook. engineering-principles stays a skill, invoked by commands; it is not
  mechanically enforced (matches the "commands = advisory, hooks = mechanical"
  design line in CLAUDE.md).

## 7. Risks / open notes

- **Config migration:** downstream repos that ran the old `/init` have
  `strictcode_*` keys. After the rename, commands read `engineering_principles_*`;
  a missing key is treated as null → the pre-flight **silently skips**. No crash, but
  those repos lose the gate until re-init. Acceptable (coderails is the source plugin;
  re-running `/init` fixes it) — document in REFERENCE.md.
- **`install.sh` / plugin discovery:** resolved — `install.sh` only `chmod +x`'s
  `skills/*/scripts/*.sh` launchers, the vendored skills ship no scripts (only
  `SKILL.md`), and `plugin.json` does not enumerate skills (auto-discovery). No
  install/uninstall/manifest change is needed.
- **Stripping Scout** loses cross-file semantic DRY/dead-code detection; the Grep
  fallback is coarser. Acceptable for self-containment; users with scout installed
  can still invoke it manually.

## 8. Verification plan

- Skill bodies contain **zero** `strictcode`, `scout-`, or `slimcode` strings after
  transform (grep).
- All four command files + REFERENCE.md + CLAUDE.md contain zero `strictcode`
  references (grep).
- `/engineering-principles` dispatch table points only at vendored sub-skills.
- `hooks/scripts/tests/run_all.sh` still passes (no hook logic touched, but confirm).
- Manual: a planning run cites the principles; a push runs the pre-flight; a
  `/workflow` review phase runs verify + simplify.

## 9. Sequencing

1. Feature branch (implementation edits hit `skills/*/SKILL.md` + `commands/*.md`,
   both blocked on `main` by `no_edit_on_main`).
2. Vendor + transform the four skills.
3. Rename refs/config keys across commands + docs + own config.
4. Add planning touchpoints (writing-plans, brainstorming).
5. Add review touchpoint (workflow.md).
6. Verify (section 8), open PR.
7. After merge + verification: remove the global `strictcode*` copies.
