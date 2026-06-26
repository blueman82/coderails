# Design — `no_edit_on_main` cross-repo false-positive fix

**Date:** 2026-06-26
**Status:** Approved (design), pre-implementation
**Files:** `hooks/scripts/no_edit_on_main.sh`, `hooks/scripts/tests/no_edit_on_main.test.sh`, `CLAUDE.md`, `docs/REFERENCE.md`

## Problem

`no_edit_on_main.sh` makes its two decisions against **two different repos**:

- **"Is this a gated source file?"** — from the **file path** (matches `*/skills/*/SKILL.md`,
  `*/commands/*.md`, and code extensions in *any* repo).
- **"Are we on a protected branch?"** — from the **session cwd's repo**
  (`dir=$(jq .cwd)`, then `git -C "$dir" branch --show-current`).

When the edited file lives in a different repo than the cwd, the two decisions
disagree. Two symptoms of this one root cause:

1. **False-positive (reported):** the coderails **wiki** (`../coderails-wiki`) has its own
   `commands/*.md` doc pages. Editing `coderails-wiki/commands/init.md` while the
   coderails cwd is on `main` matches the gated path pattern AND sees cwd-on-main →
   **blocked**, even though the file is a wiki doc and the wiki is a separate repo.
   Surfaced live during the PR #47 wiki ingest. (The wiki's *skills* are flat
   `.md` files, so only the `commands/` pattern actually collides.)
2. **Latent false-negative:** a genuine plugin `commands/*.md` edit **on main** is
   *allowed* if the cwd happens to be some other repo on a feature branch — the
   protection is keyed to the wrong repo's branch.

Regression from PR #44, which added the markdown (`commands/`/`skills/`) patterns.
Before #44 only code extensions were gated and the cwd happened to be the editing
repo, so the mismatch never bit.

## Root cause

Gated-ness is computed from the **file's path**; the branch is computed from the
**cwd's repo**. Fix: make **every** decision key off the **file's own repo**, and
require the plugin marker for the markdown arm (the one whose dir-names collide
with non-plugin repos).

## Decision

**Both decisions key off the file's repo. The plugin marker scopes ONLY the
markdown arm — the code arm stays a universal discipline.**

Two gated arms, two rules:

| Arm | Patterns | Gate when |
|---|---|---|
| **Code** | `.py .ts .tsx .js .jsx .go` | the **file's repo** is on `main`/`master` |
| **Markdown plugin-source** | `*/skills/*/SKILL.md`, `*/commands/*.md` | the file's repo is on `main`/`master` **AND** its root has `.claude-plugin/plugin.json` |

Rationale:

- **No protection gap.** Code-on-main stays blocked in *every* repo, exactly as
  before #44. The marker is applied only to the markdown arm, whose dir-names
  (`commands/`, `skills/`) legitimately appear in non-plugin repos (wikis, docs)
  where those `.md` files are documentation, not plugin source.
- The marker is the robust discriminator for "is this genuine plugin source."
  `${CLAUDE_PLUGIN_ROOT}` is **not** usable: it points at the *installed* plugin
  copy (`~/.claude/plugins/...`), not the working checkout being edited.

### Net behaviour change vs. today

1. **Wiki (and any non-plugin) `commands/*.md` / `SKILL.md` on main → now allowed.**
   This is the bug fix.
2. **Branch check keyed to the file's repo instead of cwd** (both arms). This only
   makes things *more* correct — it removes a false-positive (editing a
   feature-branch file while cwd is on main) and closes the latent false-negative.
   It opens **no** gap.

## Behaviour matrix

| File | File's repo branch | Marker? | Result |
|---|---|---|---|
| coderails `commands/push.md` | main | yes | **DENY** |
| coderails `app.py` | main | yes | **DENY** |
| coderails `commands/push.md` | feature | yes | allow |
| wiki `commands/init.md` | main | **no** | **allow** (fixes reported bug) |
| wiki `skills/foo/SKILL.md` | main | no | **allow** |
| non-plugin repo `app.py` | main | no | **DENY** (no gap — code discipline is universal) |
| coderails `commands/push.md`, cwd = other repo on feature | main (file's repo) | yes | **DENY** (fixes false-negative) |
| coderails `README.md` / `docs/*.md` / `*.json` | main | yes | allow (unchanged carve-out) |

## Mechanics

```
file = payload.tool_input.file_path            # absolute or relative; empty -> exit 0

# 1. Classify into an arm; non-gated paths exit 0.
case "$file" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.go)              arm=code ;;
  */skills/*/SKILL.md|skills/*/SKILL.md)        arm=md ;;
  */commands/*.md|commands/*.md)                arm=md ;;
  *) exit 0 ;;
esac

# 2. Resolve the file's OWN repo (cwd used only to resolve a relative path):
cwd     = payload.cwd or PWD
absfile = (file starts with "/") ? file : "$cwd/$file"
filedir = dirname(absfile)

# 3. Branch check on the FILE's repo (not cwd's) — applies to BOTH arms:
branch  = git -C "$filedir" branch --show-current
case "$branch" in main|master) ;; *) exit 0 ;; esac

# 4. Markdown arm ONLY: require the plugin marker in the file's repo:
if [ "$arm" = "md" ]; then
  root = git -C "$filedir" rev-parse --show-toplevel
  [ -f "$root/.claude-plugin/plugin.json" ] || exit 0
fi

# 5. Otherwise: emit permissionDecision=deny (unchanged reason/format + discipline log).
```

Role reversal: `cwd` stops being the branch source (the bug) and becomes only a
base for resolving a relative `file_path`. Absolute paths (Claude Code's normal
form) ignore `cwd` entirely.

## TDD plan (test-first — behaviour-changing)

`no_edit_on_main.test.sh` changes:

- **Add the marker to the existing `$REPO`** (`.claude-plugin/plugin.json`) so it
  represents a plugin repo — the existing markdown `deny` cases (`commands/*.md`,
  `SKILL.md`) stay `deny`. (Existing code-extension `deny` cases stay `deny`
  regardless of the marker, since the code arm doesn't check it.)
- **Add a second marker-less repo `$WIKI`** (its own git repo, on main, with
  `commands/` and `skills/` dirs, no `.claude-plugin/`). New cases:
  - `$WIKI` `commands/x.md` on main → **allow** (the reported bug; fails before fix)
  - `$WIKI` `skills/foo/SKILL.md` on main → **allow**
  - `$WIKI` `app.py` on main → **DENY** (proves the code arm has NO gap)
- **False-negative case:** payload whose `file_path` is in `$REPO` (plugin, on main)
  while `cwd` points at a *different* repo on a feature branch → **DENY**
  (fails before fix).
- All existing cases stay green after `$REPO` gets its marker.

## Docs to update

- `CLAUDE.md` hook-map row for `no_edit_on_main` — note the marker-scoping of the
  markdown arm + file's-repo keying.
- `docs/REFERENCE.md` `no_edit_on_main` row — same.
- Hook script header comment — explain file's-repo keying and the markdown-arm marker.

## Out of scope / guardrails

- **Do not touch `progress.json`** (separate active PR #49 thread).
- No wiki ingest needed for a hook bugfix unless behaviour is deemed notable.
- Ship via this feature branch → `/coderails:push` → review → merge.
