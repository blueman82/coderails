---
name: wiki-init
description: "Initialize an LLM Wiki for the current project — a persistent, compounding knowledge base maintained by Claude and browsed in Obsidian. Use when the user wants to set up a wiki, knowledge base, or second brain for a project. Also use when they mention Karpathy's LLM Wiki pattern, AGENTS.md, or want to organize project knowledge beyond CLAUDE.md. Triggers on 'wiki init', 'create wiki', 'knowledge base', 'set up obsidian wiki', or explicit /wiki-init."
model: sonnet
---

# Wiki Init

Bootstrap an LLM Wiki for the current project based on Karpathy's LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

The LLM builds and maintains a durable wiki. It adds links and updates pages as the project changes. The human browses the wiki in Obsidian. This reduces recurring work from raw code.

## Prerequisites

Use Obsidian to browse the vault. `qmd` is optional. If it is unavailable, read `index.md` and linked pages. Install matplotlib only if you make charts. Install other build tools only for optional tooling that needs them. This plugin has no wiki setup script.

The plugin also bundles Obsidian config files and the Marp plugin in `assets/` — these get copied into the vault in Step 3.

## Three Layers

1. **Raw sources** (immutable): The project codebase, git history, PRs, documentation. Read from these sources. Do not change the wiki when you change the code.
2. **The wiki**: LLM-generated markdown in an Obsidian vault. Claude owns this layer fully — creates pages, updates cross-references, maintains consistency.
3. **The schema** (`AGENTS-wiki-schema.md`, linked from `AGENTS.md`): Tells the LLM the wiki structure, conventions, and workflows. The user and LLM update it together.

## Instructions

### Step 1: Understand the Project

Read the project's CLAUDE.md (or equivalent). Explore the codebase. Identify the project type and the knowledge that is most useful to collect first.

### Step 2: Propose Wiki Structure

Based on the project, propose page types and directory structure. Do NOT use hardcoded types — adapt to the domain. Examples:

- **Backend service**: `services/`, `concepts/`, `entities/`, `impact/`, `investigations/`, `sources/`
- **Frontend app**: `components/`, `routes/`, `state/`, `patterns/`, `investigations/`, `sources/`
- **Library**: `modules/`, `apis/`, `patterns/`, `migrations/`, `sources/`
- **Infrastructure**: `services/`, `resources/`, `runbooks/`, `incidents/`, `sources/`

Use these for all projects: `index.md` (catalog), `log.md` (chronological), `templates/` (page skeletons), `sources/` (ingested PRs), `investigations/` (filed-back answers). Schema lives in the project directory as `AGENTS-wiki-schema.md`, linked from a slim `AGENTS.md` entry point — not in the vault.

Give the user the proposal. Include 3–5 pages for the initial wiki. Update the proposal until the user approves it.

### Step 3: Create the Vault

1. Find project name from current directory or CLAUDE.md.
2. Get the vault location from the user. Suggest `<project-parent-dir>/<project-name>-wiki/`, a sibling of the current project directory. Accept the path they give you. Set `VAULT` to that path.
3. Find the bundled `assets/` directory next to this SKILL.md file. Set `ASSETS` to its absolute path. A typical Claude Code path is `~/.claude/skills/wiki-init/assets`. Check that `obsidian-plugins/marp/main.js` exists. If it does not, stop and ask the user to install again the skill.
4. Make the vault and initialize Git.
   ```bash
   mkdir -p "$VAULT/.obsidian/plugins"
   cd "$VAULT" && git init
   ```
5. **Copy the bundled assets.** The `manifest.json`, `main.js`, and config files come from a working production vault. Do not write them by hand or from memory.
   ```bash
   cp "$ASSETS/gitignore.template" "$VAULT/.gitignore"
   cp "$ASSETS/obsidian-config/app.json" "$VAULT/.obsidian/app.json"
   cp "$ASSETS/obsidian-config/core-plugins.json" "$VAULT/.obsidian/core-plugins.json"
   cp "$ASSETS/obsidian-config/community-plugins.json" "$VAULT/.obsidian/community-plugins.json"
   cp "$ASSETS/obsidian-config/graph.json" "$VAULT/.obsidian/graph.json"
   cp "$ASSETS/obsidian-config/appearance.json" "$VAULT/.obsidian/appearance.json"
   cp -R "$ASSETS/obsidian-plugins/marp" "$VAULT/.obsidian/plugins/marp"
   ```
6. **Check that the copy succeeded before you continue.** The Marp plugin's `main.js` contains about 3.6 MB of compiled JavaScript. Without this file or if it is too small, Obsidian cannot start the plugin and gives no error.
   ```bash
   # The `main.js` file must be larger than 1 MB.
   test -f "$VAULT/.obsidian/plugins/marp/main.js" || { echo "FATAL: marp main.js missing"; exit 1; }
   test $(wc -c < "$VAULT/.obsidian/plugins/marp/main.js") -gt 1000000 || { echo "FATAL: marp main.js is too small (likely not the real plugin)"; exit 1; }
   # community-plugins.json must list "marp" (not "marp-slides" — that is a different plugin)
   grep -q '"marp"' "$VAULT/.obsidian/community-plugins.json" || { echo "FATAL: community-plugins.json missing marp entry"; exit 1; }
   ```
   If a check fails, stop. Do not improvise. Tell the user which check did not succeed and get their help.
7. Make one directory for each approved page type. Make `templates/`. Make `assets/` only if the wiki will hold charts or other generated images.
   ```bash
   cd "$VAULT" && mkdir -p templates <page-type-1> <page-type-2> ...
   # Optional, only for charts or images.
   mkdir -p assets
   ```

### Step 4: Create Foundation Files

**index.md** — content catalog. Claude reads this FIRST when answering queries. Organized by page type with `[[wiki-links]]`. Mark missing parts as "Not yet documented." Link to `AGENTS-wiki-schema.md` as the schema. Use only the project copy of `AGENTS-wiki-schema.md`. Do not add a schema.md to the vault.

**log.md** — append-only. Each entry: `## [YYYY-MM-DD] operation | description`.

**templates/** — one for each page type with YAML frontmatter skeleton.

### Step 5: Seed Initial Pages

Read the codebase and create 5-10 pages covering the most architecturally important parts. Each page:
- YAML frontmatter (title, type, created, last_updated, sources, tags)
- `[[wiki-links]]` for cross-references
- Less than 2 minutes to read
- Include relationships, patterns, and decisions. Do not include facts that the reader can get from the code.

Discuss each page with the user as you write it.

### Step 6: Create AGENTS.md and AGENTS-wiki-schema.md

Make two files in the project directory.

- **`AGENTS.md`** — a slim entry point. Add a link to `AGENTS-wiki-schema.md` as the source for wiki conventions. Keep other `AGENTS.md` content, such as a working guide.
- **`AGENTS-wiki-schema.md`** — the actual schema the LLM reads at conversation start. Include: wiki location, three layers, page types, page format, search, Ingest/Query/Lint workflows, conventions, evolution note. In Search, say that `qmd` is optional. If it is unavailable, tell the reader to use `index.md` directly. Keep `qmd` optional.

**In the Page types section of `AGENTS-wiki-schema.md`, include each directory Claude will write to.** Include `templates/` and `assets/` as structural directories.

The Coderails hook `hooks/scripts/wiki_taxonomy_gate.py` uses `wiki.schema.json` as its write allowlist. At the repo root, use `{"page_types": [...dir names], "structural_dirs": [...]}`. Keep this file and the Page types section in sync. Do this only for the vault in the plugin’s `.coderails/workflow.config.yaml`. The gate does not apply to other projects’ vaults.

If the gate refuses a write, it tells you and logs the refused directory and the approved list. If you make a directory in Step 3 and leave it out of the list, the gate refuses the first write.

The allowlist parser does not check the filesystem. For example, you can list `assets/` without making that directory in Step 3. A second check in the hook requires two or more listed directories on disk. Write the list and make the vault structure.

### Step 7: Update CLAUDE.md

Add near the top of the project's CLAUDE.md:

```markdown
## Wiki Knowledge Base

**At the start of each conversation**, read `AGENTS.md` in this directory — the entry point — which links to `AGENTS-wiki-schema.md` for wiki maintenance protocols. The <project> wiki is a durable, compounding knowledge base maintained by Claude and browsed by <user> in Obsidian. The wiki vault lives at `<vault-path-chosen-in-step-3>`.
```

### Step 8: Setup Tooling

**qmd**: Register the wiki vault as a collection and add context — only if qmd is installed. `qmd collection add` gives "Collection already exists" if you run it again. Check the collection list before you add it.
```bash
if command -v qmd >/dev/null 2>&1; then
  qmd collection list | grep -qx wiki || qmd collection add <vault-path> --name wiki
  qmd context add qmd://wiki "<description of what the wiki covers>"
else
  echo "qmd not found — skipping wiki search registration. The wiki still works via index.md; install qmd later and re-run this step to enable search."
fi
```

If qmd is installed, reindex after wiki changes with `qmd update && qmd embed`. Run `qmd update` first to find new and changed files. Used alone, `qmd embed` refreshes embeddings only for known content hashes (inferred from qmd's documented behaviour).

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

# Check for an entry for the vault.
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

On first open, the bundled assets supply the Marp plugin and all settings. The user clicks "Trust author and enable plugins" when prompted — this is the only manual step.

### Step 9: Commit and Report

Commit everything. Report: pages created, vault location, how to open in Obsidian, which source to add first.
