---
name: wiki-query
description: >-
  Use for any Coderails question, lookup, or context. Search the project's
  LLM Wiki before reading source. Also use it for slides or charts based on
  wiki knowledge. Use wiki-lint for health checks and wiki-init for setup.
---

# Wiki Query

Answer a question against the project's LLM Wiki.

**Question:** $ARGUMENTS

Spawn the installed `wiki-writer` custom agent with `spawn_agent`, passing the
question and the project location in a self-contained prompt. Collect its
result with `wait_agent`. For a specific missing check, use `send_message`
while it runs or `followup_task` after it ends. If the question above is
empty, report that and stop.

## Instructions

### Step 1: Load the Schema

The git root's `AGENTS.md` loads at session start. Read its wiki schema
section. If it links to `AGENTS-wiki-schema.md`, read that file.
Coderails keeps its schema in `AGENTS.md`. Its live page types are in
`wiki.schema.json`.
If `AGENTS.md` is not in context, walk up from the current directory to the git root.
Check each level for `AGENTS.md`; a fork can start in a project subdirectory.
If you do not find it, tell the user to invoke `$coderails-codex:wiki-init` first.
The wiki vault is a separate sibling repo, such as `../coderails-wiki`.
The project's `.coderails/workflow.config.yaml` points to it.
Do not look for `AGENTS.md` in the vault.
A fork does not need to run from inside the vault.

Read `wiki_path` and `wiki_git_worktree` from the project's
`.coderails/workflow.config.yaml`. These flat keys are not in `AGENTS.md`.
Start at the project location. Search each directory up to its git root
for the config file. The first file found wins. Set `vault` to `wiki_path`.
Resolve a relative path from the project repo root. Use an absolute path
as given.

### Step 2: Search the Wiki

1. Read `$vault/index.md`. Find pages related to the question.
2. Read those pages.
3. If `qmd` is available, use it to extend the search. Use the named `wiki`
   collection. Run `qmd query -c wiki "<question>"` for an open question.
   It combines BM25 and vector search. Run
   `qmd search -c wiki "<keywords>"` for known terms. Run
   `qmd get qmd://wiki/<file>` to read one page. Without `qmd`, use steps
   1 and 2.
4. Read raw code only if the wiki does not cover the topic.

Synthesize the answer from wiki pages with citations: "According to [[page_name]]..."

### Step 3: Answer

Answers can take different forms — choose naturally:

- **Markdown** — explanations, walkthroughs, summaries
- **Comparison table** — comparing approaches, services, patterns
- **Slide deck** (Marp format) — write a `.md` file with Marp frontmatter
  in `$vault/assets/`. The Obsidian Marp Slides plugin renders it.
- **Chart** (matplotlib) — run a Python script and save its `.png` file to
  `$vault/assets/`.

### Step 4: File Back

When the answer reveals something non-obvious or reusable:

1. Create an investigation page in `$vault/investigations/` with YAML frontmatter and `[[wiki-links]]`
2. Update `$vault/index.md`
3. Append to `$vault/log.md`: `## [YYYY-MM-DD] query-file-back | <question summary>`

**If `wiki_git_worktree` is `true`**: use a worktree branch and PR — same pattern as wiki-ingest Step 1 and Step 6.

**If `wiki_git_worktree` is `false`**: write directly and commit to the vault.

After writing, reindex if `qmd` is available: `qmd update` (refreshes all configured collections), then `qmd embed -c wiki` (`update` must run first to pick up new/changed files; `embed` alone only refreshes already-known content hashes).
Run `qmd collection add <vault-path> --name wiki` only during first-time setup when the `wiki` collection is missing; it is not routine maintenance.

Good answers compound the knowledge base. File back anything that took real effort to assemble.
