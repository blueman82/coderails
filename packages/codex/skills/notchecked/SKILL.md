---
name: notchecked
description: Audit conversation claims for statements presented as verified without supporting evidence.
---

# Find Unverified Claims

Examine the assistant's substantive claims in this conversation. Also examine the text that accompanies an explicit `$coderails-codex:notchecked` mention.

Find all claims the assistant gave as facts. For each claim, look for a tool result, a file read, or a statement from the user. List the claims with no such basis.

For each claim, give:

- The claim in one sentence.
- Why the assistant did not check it. Examples are cost, oversight, or an assumption.
- A check that can show if it is correct.

List all claims that meet these conditions. Do not defend them. If all claims have a basis, say so.
