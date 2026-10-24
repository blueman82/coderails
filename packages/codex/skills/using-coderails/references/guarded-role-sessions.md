# Guarded Codex reviewer sessions

For `source-auditor`, `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, and `preflight-scout`, write a self-contained task to a prompt file. Run the package-local launcher from the calling skill directory:

```bash
python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <prompt-file> --cwd <review-worktree>
```

The launcher supplies the tracked role instructions, read-only sandbox, disabled shell, and only that role's MCP server. Read its actual result and exit status. A failed launch or an UNSUPPORTED finding is not a completed review. Other roles can use native `spawn_agent` when their own skill permits it.

For a PR review, fetch the exact current head and use a worktree checked out at that SHA as `--cwd`; verify `git rev-parse HEAD` there before launching and recheck the PR head before posting evidence. Put the PR number, SHA, requirements, and distinct review focus in the prompt file. Do not silently substitute the current checkout or a native guarded child.
