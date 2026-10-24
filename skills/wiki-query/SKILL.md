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
invoked it. If the line above is empty, the question was never passed — report
that and stop rather than answering a question you inferred.

## Instructions

### Step 1: Load the Schema

The project's `CLAUDE.md` loads `AGENTS.md` from the git root. Read its wiki schema section or the `AGENTS-wiki-schema.md` file it links to. Coderails keeps its schema in `AGENTS.md` and its live page types in `wiki.schema.json`.

If `AGENTS.md` is not in context, search upward from the current directory to the git root. Follow the walk-up pattern in `scripts/lib/config.py`. Check each level; a fork can start in a project subdirectory. If the file is absent, tell the user to run `/wiki-init`.

The vault is a separate repo, such as `../coderails-wiki`. The project's `.coderails/workflow.config.yaml` points to it. Do not look for `AGENTS.md` in the vault. The command can run outside the vault.

The vault path and git flow are **not** read from AGENTS.md — they are the `wiki_path` and
`wiki_git_worktree` flat keys in that same project's `.coderails/workflow.config.yaml`, resolved
with the same walk-up pattern as `config_path` in `scripts/lib/config.py`: starting
from the project repo location, check each directory up to its git root for
`.coderails/workflow.config.yaml`; the first one found wins. Set `vault` to the resolved
`wiki_path` (relative to the directory containing that `workflow.config.yaml` unless already
absolute).

### Step 2: Search the Wiki

1. Read `$vault/index.md` first — scan for relevant pages
2. Read relevant wiki pages — drill into matches
3. Use `qmd` only if it is available. Otherwise, rely on steps 1–2. In the `wiki` collection, use `qmd query -c wiki "<question>"` for hybrid BM25 and vector search on open questions. Use `qmd search -c wiki "<keywords>"` for BM25 search on known terms. Use `qmd get qmd://wiki/<file>` for one page.
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

1. Create an investigation page in `$vault/investigations/` with YAML frontmatter and `[[wiki-links]]`
2. Update `$vault/index.md`
3. Append to `$vault/log.md`: `## [YYYY-MM-DD] query-file-back | <question summary>`

**If `wiki_git_worktree` is `true`**: use a worktree branch and PR — same pattern as wiki-ingest Step 1 and Step 6.

**If `wiki_git_worktree` is `false`**: write directly and commit to the vault.

After writing, reindex if `qmd` is available. Run `qmd update` first to find new or changed files. Then run `qmd embed -c wiki` to refresh embeddings. Run `qmd collection add <vault-path> --name wiki` only during first-time setup if the collection is missing.

Good answers compound the knowledge base. File back anything that took real effort to assemble.
