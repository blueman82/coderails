# install.sh Verification Run — 2026-07-20

> Historical verification record: this documents the July 2026 shell installer, not the current runtime. The Python cutover replaced `install.sh` with `install.py` and its provider-local installer modules. Current commands and dependencies are documented in [INSTALLATION.md](../INSTALLATION.md). The observations below are a record of the July run only.

## Summary

Ran `bash install.sh` on macOS (Darwin 25.3.0) to check the full root installer workflow.

## Test Environment

- **Machine**: macOS (Darwin Kernel Version 25.3.0)
- **Shell**: zsh
- **Repo**: blueman82/coderails at commit 4f8cf63
- **Tools necessary for the run**: gh, jq, git (all available ✔)

## Preflight Checks

All system checks passed:
- `gh` CLI: ✔ FOUND
- `jq`: ✔ FOUND
- `git`: ✔ FOUND
- **All systems**: 100% ✔

```console
Migration scan: NO SUPERSEDED PLUGINS — CLEAR TO INSTALL
Conflict scan: NO CONFLICTS FOUND
```

## Installation Steps

### 1. Arming Scripts (chmod)
- Marked 60+ hook scripts and command scripts as executable
- Corrected file mode bits for all `.sh` files in `hooks/scripts/`, `scripts/`, and `skills/*/scripts/`

### 2. Registering Marketplace
- ✔ Added the coderails marketplace entry in `~/.claude/settings.json`
- ✔ Removed stale settings keys: `workflow-tools`, `claude-guardrails`
- ✔ Removed stale known_marketplaces entries

### 3. Discipline Rules
- ✔ Found the rules in `~/.claude/CLAUDE.md` (idempotent — no duplication)

### 4. Memory Seeds
The installer found all four feedback files (idempotent):
- ✔ feedback_assumptions.md
- ✔ feedback_auto_mode_escalation.md
- ✔ feedback_citations.md
- ✔ feedback_memory_verify.md

Memory target: `/Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory`

## Outcome

**Status**: ✔ INSTALL COMPLETE

The install script:
1. Checked all prerequisite tools are available
2. Found no plugins that interfere with installation
3. Added the marketplace to Claude Code settings
4. Made all scripts executable
5. Kept the discipline rules and memory seeds (idempotent behavior)
6. Printed post-install instructions

## Next Steps (per the installer)

To activate the plugin in Claude Code:
1. Close and start Claude Code again
2. Run: `/plugin install coderails@coderails`
3. Run: `/plugin install pr-review-toolkit@claude-plugins-official`
4. Run: `/reload-plugins`

Per-project setup:
- Run `/coderails:init` to scaffold `workflow.config.yaml`
- Run `/coderails:test-gate-setup` (optional) to find test runners

## Verification Notes

- The `--dry-run` check showed all expected "would:" operations matching the actual install
- Idempotency confirmed: re-running would skip already-present files
- No errors or warnings during execution
- All paths resolved correctly to user's local directories
