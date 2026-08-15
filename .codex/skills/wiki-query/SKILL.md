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

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `AGENTS.md`) — use that content for conventions. The wiki schema itself (page types, page format, the three layers) lives in `AGENTS-wiki-schema.md`, which `AGENTS.md` links to; read it for the full schema. If `AGENTS.md` isn't present in context (e.g. a fresh fork with no prior context), do not assume cwd: walk up from the current directory, checking each level for `AGENTS.md`, up to the git repository root (same pattern as `coderails::config_path` in `scripts/lib/config.sh`) — a fork's cwd may be a subdirectory of the project repo. If no `AGENTS.md` is found by the git root, tell the user to run `/wiki-init` first. (The wiki vault itself, e.g. `../coderails-wiki`, is a separate sibling repo the project's `.codex/workflow.config.yaml` points to; it is not where `AGENTS.md` lives, and a fork should never need to be running from inside it.)

The vault path and git flow are **not** read from AGENTS.md — they are the `wiki_path` and
`wiki_git_worktree` flat keys in that same project's `.codex/workflow.config.yaml`, resolved
with the same walk-up pattern as `coderails::config_path` in `scripts/lib/config.sh`: starting
from the project repo location, check each directory up to its git root for
`.codex/workflow.config.yaml`; the first one found wins. Set `vault` to the resolved
`wiki_path` (relative to the directory containing that `workflow.config.yaml` unless already
absolute).

### Step 2: Search the Wiki

1. Read `$vault/index.md` first — scan for relevant pages
2. Read relevant wiki pages — drill into matches
3. Use qmd if available: `qmd search "<query>"` for ranked results
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

Good answers compound the knowledge base. File back anything that took real effort to assemble.
