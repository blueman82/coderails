---
name: cite-check
description: Re-derive a specific claim from sources only - no recall, no inference, just evidence
---

# Cite-check

Write the claim text and source rules below to a self-contained prompt file,
then run `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role source-auditor --prompt-file <file> --cwd <review-worktree>`.
Read its result and exit status. Follow [guarded role sessions](../using-coderails/references/guarded-role-sessions.md).
A native `spawn_agent` child has no source-auditor MCP server.

Re-derive the claim(s) below with durable sources you can read or produce
in this invocation. Use file contents, git output, and new command output.
You have no conversation history. Read the sources or run the commands again.
Do not use earlier tool results or statements.

No recall. No inference. No "I believe" or
"should be."

**Claim(s):** $ARGUMENTS

Check each claim independently and give each its own verdict. Use sources for that claim. Cite the source (`file:line`, tool output, or direct quote).
If the sources do not show that the full claim is correct, identify the missing facts and
what would let you check them.
