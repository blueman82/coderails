---
name: cite-check
description: Re-derive a specific claim from sources only - no recall, no inference, just evidence
---

# Cite-check

Spawn the installed `source-auditor` custom agent with `spawn_agent`, passing
the claim text and the evidence rules below. Collect its result with
`wait_agent`, use `send_input` only to request missing evidence, then
`close_agent`.

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
