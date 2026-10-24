---
name: wiki-init
description: "Initialize an LLM Wiki for the current project — a persistent, compounding knowledge base maintained by Claude and browsed in Obsidian. Use when the user wants to set up a wiki, knowledge base, or second brain for a project. Also use when they mention Karpathy's LLM Wiki pattern, AGENTS.md, or want to organize project knowledge beyond CLAUDE.md. Triggers on 'wiki init', 'create wiki', 'knowledge base', 'set up obsidian wiki', or explicit /wiki-init."
model: sonnet
---

# Wiki Init

Bootstrap an LLM Wiki for the current project based on Karpathy's LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

The core idea: instead of re-deriving knowledge from raw code on every question, the LLM incrementally builds and maintains a persistent wiki — a structured, interlinked collection of markdown files that compounds over time. The human browses it in Obsidian. The LLM does the bookkeeping.

## Prerequisites

Use Obsidian to browse the vault. `qmd` is optional: without it, read `index.md` and linked pages directly. Install matplotlib only when creating charts; install any build tools required by your chosen optional tooling. This plugin does not bundle a wiki setup script.

The plugin also bundles Obsidian config files and the Marp plugin in `assets/` — these get copied into the vault in Step 3.

## Three Layers

1. **Raw sources** (immutable): The project codebase, git history, PRs, documentation. Read from these but never modify wiki when modifying code.
2. **The wiki**: LLM-generated markdown in an Obsidian vault. Claude owns this layer entirely — creates pages, updates cross-references, maintains consistency.
3. **The schema** (`AGENTS-wiki-schema.md`, linked from `AGENTS.md`): Tells the LLM how the wiki is structured, what conventions to follow, what workflows to run. Co-evolved between human and LLM over time.

## Instructions

### Step 1: Understand the Project

Read the project's CLAUDE.md (or equivalent). Explore the codebase. Understand what kind of project this is and what knowledge would be most valuable pre-compiled.

### Step 2: Propose Wiki Structure

Based on the project, propose page types and directory structure. Do NOT use hardcoded types — adapt to the domain. Examples:

- **Backend service**: services/, concepts/, entities/, impact/, investigations/, sources/
- **Frontend app**: components/, routes/, state/, patterns/, investigations/, sources/
- **Library**: modules/, apis/, patterns/, migrations/, sources/
- **Infrastructure**: services/, resources/, runbooks/, incidents/, sources/

Common across all projects: `index.md` (catalog), `log.md` (chronological), `templates/` (page skeletons), `sources/` (ingested PRs), `investigations/` (filed-back answers). Schema lives in the project directory as `AGENTS-wiki-schema.md`, linked from a slim `AGENTS.md` entry point — not inside the vault.

Present the proposal and iterate until the user approves. Include 3-5 seed pages you'd create first.

### Step 3: Create the Vault

1. Determine project name from current directory or CLAUDE.md.
2. Ask the user where the vault should live. Default suggestion: `<project-parent-dir>/<project-name>-wiki/` (sibling of the current project directory). Accept any path they provide. Set the shell variable `VAULT` to this path.
3. Locate the skill's bundled assets. The assets live next to this SKILL.md file, in the `assets/` subdirectory. Set the shell variable `ASSETS` to the absolute path of that directory. On a typical Claude Code install this is `~/.claude/skills/wiki-init/assets`. Verify it exists and contains `obsidian-plugins/marp/main.js` before proceeding — if it doesn't, stop and ask the user to reinstall the skill.
4. Create the vault and init git:
   ```bash
   mkdir -p "$VAULT/.obsidian/plugins"
   cd "$VAULT" && git init
   ```
5. **Copy the bundled assets — do NOT hand-write any of these files.** The manifest.json, main.js, and config files are exact copies from a working production vault. Never generate them from memory:
   ```bash
   cp "$ASSETS/gitignore.template" "$VAULT/.gitignore"
   cp "$ASSETS/obsidian-config/app.json" "$VAULT/.obsidian/app.json"
   cp "$ASSETS/obsidian-config/core-plugins.json" "$VAULT/.obsidian/core-plugins.json"
   cp "$ASSETS/obsidian-config/community-plugins.json" "$VAULT/.obsidian/community-plugins.json"
   cp "$ASSETS/obsidian-config/graph.json" "$VAULT/.obsidian/graph.json"
   cp "$ASSETS/obsidian-config/appearance.json" "$VAULT/.obsidian/appearance.json"
   cp -R "$ASSETS/obsidian-plugins/marp" "$VAULT/.obsidian/plugins/marp"
   ```
6. **Verify the copy succeeded before moving on.** The Marp plugin's `main.js` is ~3.6MB of compiled JavaScript — if it's missing or tiny, Obsidian will silently fail to load the plugin:
   ```bash
   # main.js must exist and be at least 1MB
   test -f "$VAULT/.obsidian/plugins/marp/main.js" || { echo "FATAL: marp main.js missing"; exit 1; }
   test $(wc -c < "$VAULT/.obsidian/plugins/marp/main.js") -gt 1000000 || { echo "FATAL: marp main.js is too small (likely not the real plugin)"; exit 1; }
   # community-plugins.json must list "marp" (not "marp-slides" — that's a different plugin)
   grep -q '"marp"' "$VAULT/.obsidian/community-plugins.json" || { echo "FATAL: community-plugins.json missing marp entry"; exit 1; }
   ```
   If any check fails, stop. Do not improvise. Tell the user what failed and ask for help.
7. Create the wiki content directories (one per approved page type) plus `templates/`. Also create `assets/` if the project expects matplotlib charts or other generated images in the wiki — it's optional, not required for every vault:
   ```bash
   cd "$VAULT" && mkdir -p templates <page-type-1> <page-type-2> ...
   # optional, only if charts/images are expected:
   mkdir -p assets
   ```

### Step 4: Create Foundation Files

**index.md** — content catalog. Claude reads this FIRST when answering queries. Organize it by page type with `[[wiki-links]]`. Mark gaps as "Not yet documented." Name the schema source the project actually uses: `AGENTS-wiki-schema.md` for a new wiki, or the `AGENTS.md` wiki section and `wiki.schema.json` for Coderails. Do not create a separate `schema.md` in the vault.

**log.md** — append-only. Each entry: `## [YYYY-MM-DD] operation | description`.

**templates/** — one per page type with YAML frontmatter skeleton.

### Step 5: Seed Initial Pages

Read the codebase and create 5-10 pages covering the most architecturally important parts. Each page:
- YAML frontmatter (title, type, created, last_updated, sources, tags)
- `[[wiki-links]]` for cross-references
- Concise — under 2 minutes to read
- Focus on knowledge that compounds (relationships, patterns, decisions), not facts derivable from code

Discuss pages with the user as you create them — don't auto-ingest silently.

### Step 6: Create AGENTS.md and AGENTS-wiki-schema.md

Create two files in the project directory (not the wiki vault):

- **`AGENTS.md`** — a slim entry point. It points to `AGENTS-wiki-schema.md` as the source of truth for wiki conventions and, if the project already has other `AGENTS.md` content (a working guide, etc.), coexists with it rather than replacing it.
- **`AGENTS-wiki-schema.md`** — the actual schema the LLM reads at conversation start. Include: wiki location, three layers, page types, page format, search, Ingest/Query/Lint workflows, conventions, evolution note. The Search section must note that `qmd` is optional — a fallback to reading `index.md` directly — so a machine without qmd isn't left with unconditional `qmd` instructions.

**List every directory Claude will write to in the Page types section of
`AGENTS-wiki-schema.md`.** Include `templates/` and `assets/` as structural
directories, not page types.

For the Coderails plugin's **own vault**, also write `wiki.schema.json` at the
plugin repository root. Keep its `page_types` and `structural_dirs` lists
aligned with the Page types section. `hooks/scripts/wiki_taxonomy_gate.py`
reads that JSON as its write allow-list. This gate applies only to the vault
named in this plugin's `.coderails/workflow.config.yaml`. Running this skill
for another project's vault does not place that vault under this gate.

When the gate identifies the plugin's own vault, reads a valid schema, and
finds at least two listed directories on disk, it rejects a write to an
unlisted directory. The denial names that directory and the sanctioned list.
Under those conditions, a directory from Step 3 that is missing from the
lists fails on its first write. If vault identity or schema is unclear, or
fewer than two listed directories exist, the hook fails open.

A listed directory may not yet exist: the allow-list parser does not check
the filesystem. For example, you may list `assets/` even if Step 3 did not
create it. The two-directory check is separate. Listing paths cannot replace
creating most of the vault structure.

### Step 7: Update CLAUDE.md

Add near the top of the project's CLAUDE.md:

```markdown
## Wiki Knowledge Base

**At the start of every conversation**, read `AGENTS.md` in this directory — the entry point — which links to `AGENTS-wiki-schema.md` for wiki maintenance protocols. The <project> wiki is a persistent, compounding knowledge base maintained by Claude and browsed by <user> in Obsidian. The wiki vault lives at `<vault-path-chosen-in-step-3>`.
```

### Step 8: Setup Tooling

**qmd**: Register the wiki vault as a collection and add context — only if qmd is installed. `qmd collection add` errors "Collection already exists" on a rerun — guard it so re-running this step doesn't fail:
```bash
if command -v qmd >/dev/null 2>&1; then
  qmd collection list | grep -qx wiki || qmd collection add <vault-path> --name wiki
  qmd context add qmd://wiki "<description of what the wiki covers>"
else
  echo "qmd not found — skipping wiki search registration. The wiki still works via index.md; install qmd later and re-run this step to enable search."
fi
```

If qmd is installed, reindex after any wiki changes with `qmd update && qmd embed`. Run `qmd update` first — `qmd embed` alone misses new files, since it only refreshes embeddings for already-known content hashes (inferred from qmd's documented behaviour); `qmd update` is what scans for new/changed files.

**Obsidian**: Register the vault programmatically and open it:

```python
import json, os, secrets, time

registry_path = os.path.expanduser("~/Library/Application Support/obsidian/obsidian.json")
vault_path = "<absolute-vault-path>"
vault_name = os.path.basename(vault_path)

# Read or create registry
if os.path.exists(registry_path):
    with open(registry_path) as f:
        registry = json.load(f)
else:
    registry = {"vaults": {}}

# Check if already registered
already = any(v["path"] == vault_path for v in registry["vaults"].values())
if not already:
    vault_id = secrets.token_hex(8)
    registry["vaults"][vault_id] = {
        "path": vault_path,
        "ts": int(time.time() * 1000),
        "open": False
    }
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)
```

Then open it: `open "obsidian://open?vault=<vault-name>"`

On first open, the Marp plugin and all settings are already configured from the bundled assets. The user clicks "Trust author and enable plugins" when prompted — this is the only manual step.

### Step 9: Commit and Report

Commit everything. Report: pages created, vault location, how to open in Obsidian, what to ingest first.
