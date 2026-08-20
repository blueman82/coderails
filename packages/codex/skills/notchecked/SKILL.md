---
name: notchecked
description: Audit conversation claims for statements presented as verified without supporting evidence.
---

# Find Unverified Claims

Review the assistant's non-trivial claims in the current conversation. Also
review any text supplied with an explicit `$coderails-codex:notchecked` mention.

Identify every claim presented as fact that is not supported by a tool result,
an inspected file, or a fact provided by the user. For each gap, state:

- The claim, in one sentence.
- Why it was not verified, such as cost, oversight, or an unsupported assumption.
- What would verify it now.

Be ruthless. Do not defend unsupported claims. If no gaps remain, say so plainly.
