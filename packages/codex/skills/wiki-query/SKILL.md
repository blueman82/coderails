---
name: wiki-query
description: "Use when the user wants to search, query, or look up information in the project's LLM Wiki. Triggers on any phrasing like 'search wiki', 'search the wiki', 'query wiki', 'ask the wiki', 'what does the wiki say', or requests to find project-specific answers grounded in wiki content. Also triggers when the user wants to generate slides (Marp) or charts (matplotlib) drawing on wiki knowledge. Do NOT trigger for general coding questions, wiki maintenance tasks (adding, filing, ingesting, linting), or wiki initialization."
---

# Wiki Query

Answer a question against the project's LLM Wiki.

**Question:** $ARGUMENTS

Spawn the installed `wiki-writer` custom agent with `spawn_agent`, passing the
question and the project location in a self-contained prompt. Collect its
result with `wait_agent`, use `send_input` only for a specific missing check,
then `close_agent`. If the question above is empty, report that and stop rather
than inferring one.

## Instructions

### Step 1: Load the Schema

The git root's `AGENTS.md` loads at session start. Use it for project conventions. `AGENTS.md` links to `AGENTS-wiki-schema.md`. Read that file for the full wiki schema: page types, page format, and the three layers. If `AGENTS.md` is not in context, walk up from the current directory to the git root. Check each level for `AGENTS.md`; a fork can start in a project subdirectory. If you do not find it, tell the user to invoke `$coderails-codex:wiki-init` first. The wiki vault is a separate sibling repo, such as `../coderails-wiki`. The project's `.coderails/workflow.config.yaml` points to it. Do not look for `AGENTS.md` in the vault. A fork does not need to run from inside the vault.

The vault path and git flow are **not** read from AGENTS.md — they are the `wiki_path` and
`wiki_git_worktree` flat keys in that same project's `.coderails/workflow.config.yaml`, resolved
by walking up from the project repo location to its git root and checking for
`.coderails/workflow.config.yaml`; the first one found wins. Set `vault` to the resolved
`wiki_path` (relative to the directory containing that `workflow.config.yaml` unless already
absolute).

### Step 2: Search the Wiki

1. Read `$vault/index.md` first — scan for relevant pages
2. Read relevant wiki pages — drill into matches
3. `qmd` is an optional accelerator — absent, rely on steps 1–2. Use the named `wiki` collection: `qmd query -c wiki "<question>"` for hybrid BM25 + vector search on open-ended questions; `qmd search -c wiki "<keywords>"` for fast BM25-only known-term lookups; `qmd get qmd://wiki/<file>` to fetch a specific page by path.
4. Fall back to raw code/codebase only if the wiki doesn't cover the topic

Synthesize the answer from wiki pages with citations: "According to [[page_name]]..."

### Step 3: Answer

Answers can take different forms — choose naturally:

- **Markdown** — explanations, walkthroughs, summaries
- **Comparison table** — comparing approaches, services, patterns
- **Slide deck** (Marp format) — write a `.md` file with Marp frontmatter in `$vault/assets/`. Rendered by the Obsidian Marp Slides plugin
- **Chart** (matplotlib) — write and execute a Python script, save `.png` to `$vault/assets/`

### Step 4: File Back

When the answer reveals something non-obvious or reusable:

1. Create an investigation page in `$vault/wiki/investigations/` with YAML frontmatter and `[[wiki-links]]`
2. Update `$vault/index.md`
3. Append to `$vault/log.md`: `## [YYYY-MM-DD] query-file-back | <question summary>`

**If `wiki_git_worktree` is `true`**: use a worktree branch and PR — same pattern as wiki-ingest Step 1 and Step 6.

**If `wiki_git_worktree` is `false`**: write directly and commit to the vault.

After writing, reindex if `qmd` is available: `qmd update` (refreshes all configured collections), then `qmd embed -c wiki` (`update` must run first to pick up new/changed files; `embed` alone only refreshes already-known content hashes). Run `qmd collection add <vault-path> --name wiki` only during first-time setup when the `wiki` collection is missing; it is not routine maintenance.

Good answers compound the knowledge base. File back anything that took real effort to assemble.
