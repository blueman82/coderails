---
name: sync-docs
description: Compare project documentation with source and report concrete drift. Use for "sync docs", "check documentation", "documentation drift", "doc audit", or "/sync-docs". The --semantic option asks for deeper code discovery when a supported tool is available.
model: sonnet
---

# Sync docs

Compare the project's documentation with its current source. Report each
mismatch with file references and a proposed correction. Keep the report
about the project under review; do not use invented services or counts.

## Options

| Option | Result |
|---|---|
| `--check` | Report verified drift without proposed text. |
| `--suggest-updates` | Include proposed Markdown for verified gaps. |
| `--semantic` | Inspect symbols and callers when a supported semantic tool is available. |
| `--compare <section>` | Limit the comparison to one named section. |
| `--verbose` | Include relevant source lines and check details. |
| `--diagrams-only` | Check diagrams and the source they describe. |

## 1. Find the documentation

Find the project's instructions, README, architecture notes, API reference,
configuration guide, and diagrams. Use tracked paths where possible. Record
which files and sections you checked. A file outside the selected scope is
not evidence that a feature is undocumented.

Identify the source for each documented claim. Examples include a command
handler, configuration schema, installed manifest, or generated diagram
input. Record the source revision used for the comparison.

## 2. Check claims against source

Check commands, defaults, configuration values, version and service counts,
component names, links, and diagrams that appear in the selected docs.
Read the actual implementation before calling a claim wrong. A missing text
match alone does not prove drift.

For each mismatch, record:

- The exact documentation path and claim.
- The source path and behavior that contradict it.
- The effect on a reader who follows the documentation.
- The smallest text change that makes the claim accurate.

Separate a dated historical record from current operating instructions.
Preserve the historical statement; add a dated current note when needed.

## 3. Inspect omitted code when requested

With `--semantic`, use an available, supported code-navigation tool to find
symbols and callers that the selected docs might omit. If a Serena MCP
server is available and the project is active, its symbol tools can help.
Check the live tool names and argument contract before calling it; this
skill does not define a portable Serena API. If no semantic tool is
available, use repository search and source reads, and report that limit.

A symbol with no text match in documentation is a lead, not a finding.
Confirm that the behavior is public or operationally relevant before
reporting a documentation gap. Cite the source and the searched doc scope.

## 4. Report

Use this structure:

```markdown
# Documentation drift report

Source revision: <commit>
Documentation scope: <paths or sections>
Checks: <checks run and limits>

## Confirmed drift

1. <Short finding>
   - Docs: <path and claim>
   - Source: <path and observed behavior>
   - Effect: <reader impact>
   - Correction: <specific text change>

## Leads that need verification

- <Lead and missing evidence, if any>
```

Order confirmed drift by effect on the reader. Do not invent a health
score from an undefined denominator. If `--check` is set, omit the
`Correction` field. If `--suggest-updates` is set, include concise Markdown
for each confirmed correction. State when a tool, source, or target surface
was unavailable.
