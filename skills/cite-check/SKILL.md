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

Check each claim below against the current files, Git output, or the output of a new command. You have no conversation history. Read the source or run the command again. Do not use memory or inference.

**Claim(s):** $ARGUMENTS

Give a verdict for each claim and show what led to it. Give the `file:line`, tool output, or verbatim text. If the source does not show that the full claim is correct, identify the missing source. Tell the user how to check the claim.
