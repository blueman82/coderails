# AGENTS.md — Coderails Wiki Schema

This file is the schema the LLM reads at conversation start to understand how the coderails wiki is structured, maintained, and queried. It is the single source of truth for wiki conventions. Do NOT create a separate `schema.md` inside the vault.

## Wiki location

`<your-wiki-vault-path>/` (set during /wiki-init)

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
  sources/          ← ingested PR records (pr_<N>_*.md)
  templates/        ← page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md)
  assets/           ← charts and images
```

## Three layers

1. **Raw sources** (immutable): The plugin repo at `<plugin-install-path>/` (wherever you unzipped coderails) — commands, hooks, scripts, skills, install.sh, CLAUDE.md. Read from these; never modify source when updating wiki.
2. **The wiki**: LLM-generated markdown in the vault above. Claude owns this layer entirely — creates pages, updates cross-references, maintains consistency.
3. **This file (AGENTS.md)**: Tells Claude how the wiki is structured, what conventions to follow, what workflows to run. Co-evolved between the maintainer and Claude over time. The maintainer edits this file to change conventions; Claude reads it on every session.

## Page types

| Type | Directory | Naming | Purpose |
|---|---|---|---|
| command | `commands/` | `<command-name>.md` | Documents one slash command: what it does, config fields, scripts invoked |
| hook | `hooks/` | `<script-name>.md` | Documents one hook script: event, mode, logic, block condition |
| skill | `skills/` | `<skill-name>.md` | Documents one skill: purpose, trigger phrases, phases, failure modes encoded |
| design | `design/` | `<topic>.md` | Architectural decisions and invariants; evergreen |
| investigation | `investigations/` | `<topic>_<YYYY-MM-DD>.md` | Point-in-time analysis filed during a workflow session; may be superseded |
| source | `sources/` | `pr_<N>_<slug>.md` | Immutable record of a merged PR, created by `/wiki-ingest` |

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
- Use `[[wiki-links]]` for all cross-references between wiki pages.
- Keep pages concise — under 2 minutes to read.
- Focus on knowledge that compounds (relationships, decisions, patterns), not facts derivable directly from reading the source code.
- Confidence-label non-trivial assertions: `(verified)` (source cited), `(inferred)` (pattern-matched), `(guess)` (explicit speculation).

## Enforcement model distinction

The single most important design invariant in this plugin:

- **Hooks = mechanical enforcement.** They run automatically on lifecycle events and can block (exit 2 / permissionDecision: deny) regardless of Claude's cooperation. Use hooks for invariants that must hold unconditionally.
- **Slash commands = advisory.** Claude chooses to invoke them. Use commands to encode workflow, not to enforce it.

If a future contributor asks "should this be a hook or a command?" — the answer is: if it must be enforced even when Claude doesn't cooperate, it's a hook. See [[enforcement-model]].

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

### Lint

Use `/wiki-lint` from the coderails plugin. Always run after ingest. Checks for: orphaned pages (linked but not created), stale `last_updated` dates, missing cross-references, contradictions between pages.

Fix anything directly related to the current PR; defer unrelated findings.

## Evolution note

This file is co-evolved. When conventions change — new page types, new frontmatter fields, naming rule changes — update this file first, then update affected pages in the vault. The maintainer edits this file; Claude reads it. The wiki is a living system, not a snapshot.
