---
name: wiki-init
description: "Initialize an LLM Wiki for the current project — a persistent, compounding knowledge base maintained by Codex and browsed in Obsidian. Use when the user wants to set up a wiki, knowledge base, or second brain for a project. Also use when they mention Karpathy's LLM Wiki pattern, AGENTS.md, or want to organize project knowledge beyond AGENTS.md. Triggers on 'wiki init', 'create wiki', 'knowledge base', 'set up obsidian wiki', or $coderails-codex:wiki-init."
---

# Wiki Init

Bootstrap an LLM Wiki for the current project based on Karpathy's LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

The LLM builds and maintains a wiki of linked Markdown files.
It keeps knowledge from earlier work so the LLM can answer future questions without deriving it from raw code again.
The human browses it in Obsidian.
The LLM does the bookkeeping.

## Prerequisites

Use Obsidian to browse the vault.
`qmd` is optional: without it, read `index.md` and linked pages directly.
Install matplotlib only when you make charts. Install the build tools necessary for the optional tools you select.
This plugin does not bundle a wiki setup script.

The plugin also bundles Obsidian config files and the Marp plugin in `assets/` — these get copied into the vault in Step 3.

## Three Layers

1. **Raw sources** (immutable): The project codebase, Git history, PRs, and documentation.
   Read these sources. Do not change the wiki when you change code.
2. **The wiki**: Markdown the LLM writes in an Obsidian vault.
   Codex owns this layer. It makes pages, updates links, and makes sure the pages agree.
3. **The schema** (`AGENTS-wiki-schema.md`, linked from `AGENTS.md`): It gives the LLM the wiki structure, conventions, and workflows.
   The user and LLM develop it together.

## Instructions

### Step 1: Understand the Project

Read the project's AGENTS.md (or equivalent). Examine the codebase.
Identify the project type and which knowledge is most useful to record first.

### Step 2: Propose Wiki Structure

Based on the project, propose page types and directory structure. Do NOT use hardcoded types — adapt to the domain. Examples:

- **Backend service**: `services/`, `concepts/`, `entities/`, `impact/`, `investigations/`, `sources/`
- **Frontend app**: `components/`, `routes/`, `state/`, `patterns/`, `investigations/`, `sources/`
- **Library**: modules/, apis/, patterns/, migrations/, sources/
- **Infrastructure**: services/, resources/, runbooks/, incidents/, sources/

All projects use `index.md` (catalog), `log.md` (chronological), `templates/` (page skeletons), `sources/` (PR records), and `investigations/` (answers filed from queries).
Schema lives in the project directory as `AGENTS-wiki-schema.md`, linked from a slim `AGENTS.md` entry point — not in the vault.

Give the user the proposal. Update it until the user approves. List the 3–5 pages you propose to make first.

### Step 3: Create the Vault

1. Find the project name in the current directory name or AGENTS.md.
2. Let the user select the vault path. Suggest `<project-parent-dir>/<project-name>-wiki/` as the default.
   This is a sibling of the project directory. Accept the path the user gives.
   Set `VAULT` to that path in the shell.

3. Find the bundled `assets/` subdirectory next to this SKILL.md file.
   Set `ASSETS` to its absolute path in the shell. A typical Codex install uses `~/.codex/skills/wiki-init/assets`.
   Check that the directory contains `obsidian-plugins/marp/main.js`.
   If it does not, stop and tell the user to install the skill again.

4. Make the vault and init git:
   ```bash
   mkdir -p "$VAULT/.obsidian/plugins"
   cd "$VAULT" && git init
   ```
5. **Copy the bundled assets. Do not write these files by hand or from memory.**
   The bundled `manifest.json`, `main.js`, and config files are unchanged copies from a production vault that works.
   ```bash
   cp "$ASSETS/gitignore.template" "$VAULT/.gitignore"
   cp "$ASSETS/obsidian-config/app.json" "$VAULT/.obsidian/app.json"
   cp "$ASSETS/obsidian-config/core-plugins.json" "$VAULT/.obsidian/core-plugins.json"
   cp "$ASSETS/obsidian-config/community-plugins.json" "$VAULT/.obsidian/community-plugins.json"
   cp "$ASSETS/obsidian-config/graph.json" "$VAULT/.obsidian/graph.json"
   cp "$ASSETS/obsidian-config/appearance.json" "$VAULT/.obsidian/appearance.json"
   cp -R "$ASSETS/obsidian-plugins/marp" "$VAULT/.obsidian/plugins/marp"
   ```
6. **Check the copy before you continue.** The Marp plugin's `main.js` contains about 3.6 MB of compiled JavaScript.
   If there is no file or it is too small, Obsidian does not activate the plugin and gives no error:
   ```bash
   # Check for `main.js` and a byte count above 1000000
   test -f "$VAULT/.obsidian/plugins/marp/main.js" || { echo "FATAL: marp main.js missing"; exit 1; }
   test $(wc -c < "$VAULT/.obsidian/plugins/marp/main.js") -gt 1000000 || { echo "FATAL: marp main.js is too small (likely not the real plugin)"; exit 1; }
   # `community-plugins.json` must list "marp". "marp-slides" is a different plugin.
   grep -q '"marp"' "$VAULT/.obsidian/community-plugins.json" || { echo "FATAL: community-plugins.json missing marp entry"; exit 1; }
   ```
   If a check does not succeed, stop. Do not improvise. Tell the user the error and ask for help.
7. Make one wiki content directory for each approved page type. Also make `templates/`.
   Also make `assets/` if the project expects matplotlib charts or other generated images in the wiki — it is optional, not necessary for each vault:
   ```bash
   cd "$VAULT" && mkdir -p templates <page-type-1> <page-type-2> ...
   # Optional. Use this only if the wiki will include charts or images.
   mkdir -p assets
   ```

### Step 4: Create Foundation Files

**index.md** — content catalog. Codex reads this first for queries. Organize it by page type with `[[wiki-links]]`.
Mark missing content as "Not yet documented." Give `AGENTS-wiki-schema.md` as the schema location.
Use only the project directory's `AGENTS-wiki-schema.md` for the schema. Do not add a `schema.md` to the vault.

**log.md** — append-only. Each entry: `## [YYYY-MM-DD] operation | description`.

**templates/** — one file for each page type with a YAML frontmatter skeleton.

### Step 5: Seed Initial Pages

Read the codebase and create 5-10 pages covering the most architecturally important parts. Each page:
- YAML frontmatter (title, type, created, last_updated, sources, tags)
- `[[wiki-links]]` for cross-references
- Short. The reader can finish it in less than 2 minutes
- Record knowledge that accumulates (relationships, patterns, decisions). Do not include facts a reader can get directly from code

Discuss pages with the user as you make them — do not auto-ingest silently.

### Step 6: Create AGENTS.md and AGENTS-wiki-schema.md

Make two files in the project directory (not the wiki vault):

- **`AGENTS.md`** — a slim entry point.
  Point to `AGENTS-wiki-schema.md` as the authoritative source for wiki conventions.
  Keep existing `AGENTS.md` content, such as the working guide.
- **`AGENTS-wiki-schema.md`** — the actual schema the LLM reads at conversation start.
  Include: wiki location, three layers, page types, page format, search, Ingest/Query/Lint workflows, conventions, evolution note.
  In the Search section, say that `qmd` is optional.
  If a machine does not have `qmd`, tell the reader to use `index.md` directly.

**List each directory Codex can write to in the Page types section of `AGENTS-wiki-schema.md`.** Include `templates/` and `assets/` as structural directories, not page types.
The Coderails `hooks/scripts/wiki_taxonomy_gate.py` hook reads `wiki.schema.json` (repo root: `{"page_types": [...dir names], "structural_dirs": [...]}`) as its write allow-list.
Write that file with the Page types section, and keep them in step.

The hook applies only to the ONE vault named in the plugin's own `.coderails/workflow.config.yaml`.
The gate does not apply to a vault for a different project.
If the gate denies a write, it logs the rejected directory and the sanctioned list.
If Step 3 made a directory and the Page types section does not include it, the gate refuses the first write.

You can list a directory before creating it.
The allow-list parser does not check the filesystem.
For example, list `assets/` here if Step 3 did not make it.
The hook also checks that a minimum of two listed directories are on disk.
Make the other vault directories as specified in Step 3.

### Step 7: Update AGENTS.md

Add near the top of the project's AGENTS.md:

```markdown
## Wiki Knowledge Base

**At the start of each conversation**, read `AGENTS.md` in this directory.
Follow its link to `AGENTS-wiki-schema.md` for wiki maintenance instructions.
Codex maintains the <project> wiki and adds knowledge to it as work continues.
The <user> browses the wiki in Obsidian. The vault is at `<vault-path-chosen-in-step-3>`.
```

### Step 8: Setup Tooling

**qmd**: If `qmd` is installed, register the wiki vault as a collection and add context.
`qmd collection add` can give "Collection already exists" when you run it again.
Check for the collection first:
```bash
if command -v qmd >/dev/null 2>&1; then
  qmd collection list | grep -qx wiki || qmd collection add <vault-path> --name wiki
  qmd context add qmd://wiki "<description of what the wiki covers>"
else
  echo "qmd not found — skipping wiki search registration. The wiki still works via index.md; install qmd later and re-run this step to enable search."
fi
```

If `qmd` is installed, reindex after wiki changes with `qmd update && qmd embed`.
Run `qmd update` first to find new or changed files. `qmd embed` alone refreshes only known content hashes (inferred from qmd's documented behaviour).

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

# Check for an existing registration
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

On first open, the bundled assets supply the Marp plugin and all settings.
When Obsidian prompts the user, the user clicks "Trust author and enable plugins". This is the only manual step.

### Step 9: Commit and Report

Commit everything. Report the pages you made, the vault location, and how to open it in Obsidian.
Tell the user which source to add first.
