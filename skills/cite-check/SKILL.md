---
name: cite-check
description: Re-derive a specific claim from sources only - no recall, no inference, just evidence
agent: coderails:source-auditor
context: fork
background: false
argument-hint: <claim to verify>
---

# Cite-check

Re-derive the claim(s) below using only durable sources you can read or produce
right now — file contents, git output, and fresh command output. You have no
conversation history, so do not rely on prior tool results or anything said
earlier; go read or re-run it. No recall. No inference. No "I believe" or
"should be."

**Claim(s):** $ARGUMENTS

Treat each claim independently and give each its own verdict (evidence for one
never carries another). For each, cite the source (`file:line`, tool output,
exact quote). If a claim cannot be fully sourced, state precisely what is
missing and what would be needed to verify it.
