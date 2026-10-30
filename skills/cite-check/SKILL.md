---
name: cite-check
description: Re-derive a specific claim from sources only - no recall, no inference, just evidence
agent: coderails:source-auditor
context: fork
background: false
argument-hint: <claim to verify>
effort: high
---

# Cite-check

Re-derive each claim below from current file contents, git output, or fresh
command output. You have no conversation history. Read or rerun the source
instead of relying on prior results. Do not use recall or inference.

**Claim(s):** $ARGUMENTS

Give each claim its own verdict and evidence. Cite `file:line`, tool output,
or an exact quote. If a claim lacks full support, state what source is
missing and how to verify it.
