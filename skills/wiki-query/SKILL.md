---
name: wiki-query
description: >-
  Use for project questions that need the LLM Wiki. Trigger phrases include
  "search wiki", "search the wiki", "query wiki", "ask the wiki", and
  "what does the wiki say".
  Also use it for slides or charts based on wiki knowledge. Do not use it
  for general coding questions, wiki maintenance, or wiki setup.
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

The project's `CLAUDE.md` loads `AGENTS.md` from the git root. Read its wiki
schema section. If it links to `AGENTS-wiki-schema.md`, read that file.
Coderails keeps its schema in `AGENTS.md`. Its live page types are in
`wiki.schema.json`.

If `AGENTS.md` is not in context, search from the current directory up to
the git root. Check each level, as `scripts/lib/config.py` does for config.
A fork can start in a project subdirectory. If the file is absent, tell
the user to run `/wiki-init`.

The vault is a separate repo, such as `../coderails-wiki`.
The project's `.coderails/workflow.config.yaml` points to it.
Do not look for `AGENTS.md` in the vault. The command can run outside it.

Read `wiki_path` and `wiki_git_worktree` from the project's
`.coderails/workflow.config.yaml`. These flat keys are not in `AGENTS.md`.
Start at the project location. Search each directory up to its git root
for the config file, as `config_path` does. The first file found wins.
Set `vault` to `wiki_path`. Resolve a relative path from the project repo
root. Use an absolute path as given.

### Step 2: Search the Wiki

1. Read `$vault/index.md`. Find pages related to the question.
2. Read those pages.
3. If `qmd` is available, use it to extend the search. Use
   `qmd query -c wiki "<question>"` for an open question. It combines BM25
   and vector search. Use `qmd search -c wiki "<keywords>"` for known terms.
   Use `qmd get qmd://wiki/<file>` to read one page. Without `qmd`, use
   steps 1 and 2.
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

After writing, reindex if `qmd` is available. Run `qmd update` first to find new or changed files. Then run `qmd embed -c wiki` to refresh embeddings. Run `qmd collection add <vault-path> --name wiki` only during first-time setup if the collection is missing.

Good answers compound the knowledge base. File back anything that took real effort to assemble.
