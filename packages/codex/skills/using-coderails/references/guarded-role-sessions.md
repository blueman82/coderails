# Guarded Codex reviewer sessions

For `source-auditor`, `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, and `preflight-scout`, write a self-contained task to a prompt file. Run the package-local launcher from the calling skill directory:

```bash
python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <prompt-file> --cwd <review-worktree>
```

The launcher supplies the tracked role instructions, read-only sandbox, disabled shell, and only that role's MCP server. Read its actual result and exit status. If the launch fails or gives an UNSUPPORTED result, the inspection is not complete. Other roles can use native `spawn_agent` when their own skill permits it.

To examine a PR, fetch the current head and use a worktree at that SHA as `--cwd`. Check `git rev-parse HEAD` there before you launch the role. Check the PR head again before you post the results. Put the PR number, SHA, requirements, and topics for this role to examine in the prompt file. Do not silently use the current checkout or a native guarded child as a replacement.
