# AGENTS-wiki-schema.md — the coderails wiki schema

Based on the LLM Wiki pattern:
https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

Split out of `AGENTS.md` (2026-07-17) to keep that file a slim working guide.
This file is the single source of truth for coderails wiki conventions — how
the wiki is structured, maintained, and queried. `AGENTS.md` is still the
entry point; it links here.

## The coderails wiki schema

This is the single source of truth for wiki conventions. Do NOT create a separate
`schema.md` inside the vault.

## Wiki location

`../coderails-wiki` (set during /wiki-init)

```yaml
git:
  worktree: false   # personal wiki, no PR ceremony — write and commit directly
wiki:
  supervision: autonomous   # wiki-ingest writes and commits without a discuss-first pause.
                             # Default when this field is absent is `discuss` (Step 3's
                             # "discuss with the user" requirement) — this project opts
                             # into autonomous curation explicitly; it is not the shipped
                             # default for other coderails installs.
```

Vault structure:
```
coderails-wiki/
  index.md          ← content catalog; read this first on every wiki query
  log.md            ← append-only chronological record
  commands/         ← one page per slash command
  hooks/            ← one page per hook script
  skills/           ← one page per skill
  design/           ← architectural decisions and invariants
  investigations/   ← point-in-time filed analyses (<topic>_<YYYY-MM-DD>.md)
  sources/          ← ingested PR records (pr_<N>_<slug>.md)
  templates/        ← page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md)
  assets/           ← charts and images
```

## Three layers

1. **Raw sources** (immutable): The plugin repo at `<plugin-install-path>/` (wherever you unzipped coderails) — commands, hooks, scripts, skills, install.sh, CLAUDE.md. Read from these; never modify source when updating wiki.
2. **The wiki**: LLM-generated markdown in the vault above. Claude owns this layer entirely — creates pages, updates cross-references, maintains consistency.
3. **AGENTS-wiki-schema.md** (this file): Tells Claude how the wiki is structured, what conventions to follow, what workflows to run. Co-evolved between the maintainer and Claude over time. The maintainer edits this file to change conventions; `AGENTS.md` is the slim entry point that links here.

## Page types

> **This section is live enforcement config, not just documentation.** At
> runtime, `hooks/scripts/wiki_taxonomy_gate.sh` parses everything from this
> heading up to the next `## ` heading as its write allow-list: any
> backticked directory-slash token found anywhere in that span sanctions
> that directory for writes. Adding, removing, or reformatting such a token
> — in a table cell or in surrounding prose — changes what the gate
> permits, not just what this doc says.

| Type | Directory | Naming | Purpose |
|---|---|---|---|
| command | `commands/` | `<command-name>.md` | Documents one slash command: what it does, config fields, scripts invoked |
| hook | `hooks/` | `<script-name>.md` | Documents one hook script: event, mode, logic, block condition |
| skill | `skills/` | `<skill-name>.md` | Documents one skill: purpose, trigger phrases, phases, failure modes encoded |
| design | `design/` | `<topic>.md` | Architectural decisions and invariants; evergreen |
| investigation | `investigations/` | `<topic>_<YYYY-MM-DD>.md` | Point-in-time analysis filed during a workflow session; may be superseded |
| source | `sources/` | `pr_<N>_<slug>.md` | Immutable record of a merged PR, created by `/wiki-ingest` |

**Not page types — structural directories.** These hold skeletons and
charts, carry no frontmatter, and are never `[[wiki-link]]`ed:

| Directory | Naming | Purpose |
|---|---|---|
| `templates/` | `<page-type>.md` | Page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md) with the YAML frontmatter shape |
| `assets/` | freeform | Charts and images generated for wiki pages (e.g. matplotlib output) |
| `dashboard-runs/` | `<routine>.md` | Scheduled-routine run notes, `type: routine-run`, written by `skills/dashboard/runner` |

`dashboard-runs/` content is operational output, not wiki content — it
follows none of the page-format rules below, is never linked via
`[[wiki-links]]`, and is not touched by `/wiki-ingest` or `/wiki-lint`.
The `type: routine-run` frontmatter is specific to the runner's own
notes — the Obsidian plugin's direct-exec path writes separate per-run
notes into the same `dashboard-runs/` folder with
`status: running|done|failed` frontmatter and no `type` field; treat
both as non-wiki operational output regardless of frontmatter shape.
See [`docs/routines.md`](./docs/routines.md) for what they're for.

## Page format

Every page must have:

```yaml
---
title: "<Page title>"
type: <command|hook|skill|design|investigation|source>
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
sources: []        # list of PR source page paths that informed this page
tags: []           # freeform list
---
```

Body rules:
- Use `[[wiki-links]]` for all cross-references between wiki pages — `[[page_name]]` with no directory prefix; Obsidian resolves the target.
- Keep pages concise — under 2 minutes to read.
- Focus on knowledge that compounds (relationships, decisions, patterns), not facts derivable directly from reading the source code.
- Confidence-label non-trivial assertions: `(verified)` (source cited), `(inferred)` (pattern-matched), `(guess)` (explicit speculation).
- Flag contradictions inline as `> ⚠️ CONTRADICTION: <description>`. `/wiki-lint` scans for this marker — write it whenever you find a page that conflicts with newer or more accurate information.

## Enforcement model (wiki lens)

The full treatment — hooks vs commands, the enforcement ceiling, and the
skills↔hooks seam convention — lives in the **Two enforcement mechanisms**
section of the repo working guide in [`AGENTS.md`](./AGENTS.md). For wiki purposes the rule is: when documenting a hook
page vs a command page, record *which* mechanism it is and *what it can/can't
guarantee*; link the page to [[enforcement-model]] and cite the ceiling caveats
verbatim so they aren't re-opened as findings.

## Workflows

### Ingest (after every PR merge)

Use `/wiki-ingest` from the coderails plugin. Never write wiki pages directly for PR content.

1. Create `sources/pr_<N>_<slug>.md` using `templates/source.md`
2. Update affected concept/design/hook/command/skill pages with new knowledge
3. Append an entry to `log.md`: `## [YYYY-MM-DD] ingest | PR #N merged: <description>`
4. Update `index.md` if new pages were created
5. Then run `/wiki-lint`

### Query

Use `/wiki-query` from the coderails plugin. The skill reads `index.md` first, then fetches relevant pages, then answers the question with citations.

If answering a question reveals something non-obvious, create an investigation page in `investigations/` to file the finding back — that is the birth condition for a new investigation page.

### Lint

Use `/wiki-lint` from the coderails plugin. Always run after ingest. Checks for: orphaned pages (linked but not created), stale `last_updated` dates, missing cross-references, contradictions between pages.

Fix anything directly related to the current PR; defer unrelated findings.

## Search

`qmd` is an optional accelerator, not a requirement — if it isn't installed, search falls back to reading `index.md` directly, and the commands below apply only when `qmd` is present.

Once the vault outgrows reading `index.md` directly, use `qmd` to search it:

- `qmd query "<question>"` — hybrid BM25 + vector search with reranking (inferred from `qmd --help`'s query-syntax section, which accepts separate `lex:`/`vec:` lines but doesn't name the fusion explicitly). Best for open-ended questions.
- `qmd search "<keywords>"` — BM25 only, fast (verified: `qmd --help` states "Full-text BM25 keywords (no LLM)"). Best for known-term lookups.
- `qmd get <file>` — fetch a specific page by path.

**Reindex rule**: after wiki changes, run `qmd update && qmd embed`. `qmd embed` alone misses new files — it only refreshes embeddings for already-known content hashes (inferred from qmd's documented behaviour). `qmd update` is what scans for new/changed files; it must run first.

`qmd collection add` is first-time setup only — it errors "Collection already exists" on reruns (verified: observed on a scratch collection). Don't run it as part of routine maintenance.

## Conventions

- Frontmatter tags are lowercase and hyphenated.
- One concept per page — split a page that covers too much.
- Source pages reference the PR number and key files changed.

## Exploration boundary

Subagent/code exploration explores code; the wiki captures understanding. Use exploration when a wiki operation hits a specific gap — a query found no page, an ingest touches unfamiliar code, or a lint finds a page you have specific reason to doubt. Do NOT use it to routinely validate wiki content: the wiki is trusted by default and corrected by evidence, not by standing patrols.

## Evolution note

This file is co-evolved. When conventions change — new page types, new frontmatter fields, naming rule changes — update this file first, then update affected pages in the vault. The maintainer edits this file; Claude reads it. The wiki is a living system, not a snapshot.
