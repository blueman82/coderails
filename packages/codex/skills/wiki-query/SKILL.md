---
name: wiki-query
description: "Use when the user wants to search, query, or look up information in the project's LLM Wiki. Triggers on any phrasing like 'search wiki', 'search the wiki', 'query wiki', 'ask the wiki', 'what does the wiki say', or requests to find project-specific answers grounded in wiki content. Also triggers when the user wants to generate slides (Marp) or charts (matplotlib) drawing on wiki knowledge. Do NOT trigger for general coding questions, wiki maintenance tasks (adding, filing, ingesting, linting), or wiki initialization."
---

# Wiki Query

Answer a question against the project's LLM Wiki.

**Question:** $ARGUMENTS

If the question above is empty, report that and stop. Do not infer a question.

Start the installed `wiki-writer` custom agent with `spawn_agent`.
Give it the question and the project location in a self-contained prompt.
Collect its result with `wait_agent`. Use `send_input` only if you can name a missing check.
Then use `close_agent`.

## Instructions

### Step 1: Load the Schema

At session start, Codex reads the project root's `AGENTS.md` into context. Use that file for project conventions.
Read its linked `AGENTS-wiki-schema.md` for the full schema, which defines page types, page format, and the three layers.

If the context does not contain `AGENTS.md`, start at the current directory and check each parent up to the Git root.
If you find no `AGENTS.md`, tell the user to invoke `$coderails-codex:wiki-init` first.
The vault is a sibling repository, for example `../coderails-wiki`. Find `AGENTS.md` in the project repository.
The session can use the vault from the project directory.

Read the vault path and Git flow from the flat `wiki_path` and `wiki_git_worktree` keys in `.coderails/workflow.config.yaml`.
Check for that config from the project repository location up to its Git root. Use the first config you find.
Set `vault` to the resolved `wiki_path`. If that path is relative, resolve it from the directory containing `workflow.config.yaml`.

### Step 2: Search the Wiki

1. Read `$vault/index.md` first — scan for related pages
2. Read related wiki pages — drill into matches
3. If `qmd` is unavailable, use steps 1–2. If it is available, use the named `wiki` collection.
   Use `qmd query -c wiki "<question>"` for hybrid BM25 + vector lookup on open-ended questions.
   Use `qmd search -c wiki "<keywords>"` for fast BM25-only lookups of known terms.
   Use `qmd get qmd://wiki/<file>` to fetch a page by path.
4. Read the code only if the wiki does not include the topic.

Synthesize the answer from wiki pages with citations: "According to [[page_name]]..."

### Step 3: Answer

Use the format that fits the question:

- **Markdown** — explanations, walkthroughs, summaries
- **Table** — compare approaches, services, and patterns
- **Marp deck** — write a `.md` file with Marp frontmatter
  in `$vault/assets/`. The Obsidian Marp Slides plugin renders it.
- **Chart** (matplotlib) — write and run a Python script, then write its `.png`
  file to `$vault/assets/`.

### Step 4: File Back

If the answer gives new information or information that can help on a future task:

1. Make an investigation page in `$vault/wiki/investigations/` with YAML frontmatter and `[[wiki-links]]`
2. Update `$vault/index.md`
3. Append to `$vault/log.md`: `## [YYYY-MM-DD] query-file-back | <question summary>`

**If `wiki_git_worktree` is `true`**: use a worktree branch and PR — same pattern as wiki-ingest Step 1 and Step 6.

**If `wiki_git_worktree` is `false`**: write directly and commit to the vault.

After writing, reindex if `qmd` is available. Run `qmd update` first, then run `qmd embed -c wiki`.
The update refreshes all configured collections and finds new or changed files.
The embed command alone refreshes only known content hashes.

If there is no `wiki` collection during first-time setup, run `qmd collection add <vault-path> --name wiki`.
Do not run it as part of usual maintenance.

File back answers that took substantial work to assemble.
