---
name: wiki-query
description: "Use when the user wants to search, query, or look up information in the project's LLM Wiki. Triggers on any phrasing like 'search wiki', 'search the wiki', 'query wiki', 'ask the wiki', 'what does the wiki say', or requests to find project-specific answers grounded in wiki content. Also triggers when the user wants to generate slides (Marp) or charts (matplotlib) drawing on wiki knowledge. Do NOT trigger for general coding questions, wiki maintenance tasks (adding, filing, ingesting, linting), or wiki initialization."
context: fork
agent: coderails:wiki-writer
background: false
argument-hint: <question>
model: sonnet
---

# Wiki Query

Answer a question against the project's LLM Wiki.

**Question:** $ARGUMENTS

This skill runs in a forked context with no access to the conversation that
invoked it. If the line above is empty, this skill got no question. Report that and stop.

## Instructions

### Step 1: Load the Schema

At session start, read the project's Git-root `AGENTS.md` as directed by its `CLAUDE.md`. Use it for conventions. For page types, page format, and the three layers, follow the link to `AGENTS-wiki-schema.md` in `AGENTS.md`. Read the full schema.

If the fork has no `AGENTS.md` in context, look in the current directory and its parents up to the Git root. Use the same pattern as `config_path` in `scripts/lib/config.py`. A fork can start in a subdirectory, so check the path to `AGENTS.md`. If you do not find `AGENTS.md` by the Git root, tell the user to run `/wiki-init` first.

Use the project's `AGENTS.md`. The wiki vault is a sibling repo such as `../coderails-wiki`. The project config `.coderails/workflow.config.yaml` points to it. You can run the fork from the project repo.

Get the vault path and Git flow from the flat keys `wiki_path` and `wiki_git_worktree` in the project's `.coderails/workflow.config.yaml`. Follow the same pattern as `config_path` in `scripts/lib/config.py`.

Starting from the project repo location, check each directory up to the Git root for `.coderails/workflow.config.yaml`. Use the first file you find. Set `vault` to `wiki_path`. If it is a relative path, resolve it from the directory that contains `workflow.config.yaml`.

### Step 2: Search the Wiki

1. Read `$vault/index.md` first — scan for related pages
2. Read related wiki pages — drill into matches
3. Use `qmd` to speed up lookup. If unavailable, use steps 1–2. Use the named `wiki` collection. Run `qmd query -c wiki "<question>"` for hybrid BM25 and vector lookup on open-ended questions. Run `qmd search -c wiki "<keywords>"` for fast BM25-only lookup of known terms. Run `qmd get qmd://wiki/<file>` to get a page by path.
4. Fall back to raw code/codebase only if the wiki does not include the topic

Synthesize the answer from wiki pages with citations: "According to [[page_name]]..."

### Step 3: Answer

Select an answer format that fits the question.

- **Markdown** — explanations, walkthroughs, summaries
- **Table** — compare approaches, services, and patterns
- **Marp deck** — write a `.md` file with Marp frontmatter in `$vault/assets/`. The Obsidian Marp Slides plugin displays it.
- **Chart** (matplotlib) — write and execute a Python script, save `.png` to `$vault/assets/`

### Step 4: File Back

If the answer contains a new fact or information useful to future work, add it to the wiki.

1. Make an investigation page in `$vault/wiki/investigations/` with YAML frontmatter and `[[wiki-links]]`
2. Update `$vault/index.md`
3. Append to `$vault/log.md`: `## [YYYY-MM-DD] query-file-back | <question summary>`

**If `wiki_git_worktree` is `true`**: use a worktree branch and PR — same pattern as wiki-ingest Step 1 and Step 6.

**If `wiki_git_worktree` is `false`**: write directly and commit to the vault.

After writing, reindex if `qmd` is available. Run `qmd update` to refresh all configured collections and include new or changed files. Then run `qmd embed -c wiki`. Without the first command, `update`, the second command, `embed`, refreshes only known content hashes. Run `qmd collection add <vault-path> --name wiki` only during first-time setup if you have no `wiki` collection.

Add answers to the wiki when they took substantial work to assemble.
