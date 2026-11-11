# Codex Tool Mapping

Skills speak in steps ("dispatch a subagent", "create a todo", "read a file"). On Codex these resolve to the tools below.

| Skill instruction | Codex equivalent |
|----------------------|------------------|
| Read a file | `shell` (e.g., `cat`, `head`, `tail`) — Codex reads files through shell |
| Make, edit, or remove a file | `apply_patch` (uses a structured diff) |
| Run a shell command | `shell` |
| Find text in files | `shell` (e.g., `grep`, `rg`) |
| Find files by name | `shell` (e.g., `find`, `ls`) |
| Fetch a URL | `shell` with `curl` / `wget` — Codex has no native fetch tool |
| Find information on the web | `web_search` is on by default. In `config.toml`, set the top-level `web_search` to `live`, `cached`, or `disabled`. |
| Invoke a skill | Codex loads skills. Follow their instructions. |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | `spawn_agent` (see [Multi-agent settings](#subagent-dispatch-requires-multi-agent-support)) |
| Multiple parallel dispatches | Multiple `spawn_agent` calls in one response |
| Wait for subagent result | `wait_agent` |
| Free up subagent slot when done | `close_agent` |
| Task tracking ("create a todo", "mark complete") | `update_plan` |

## Instructions file

When a skill mentions "your instructions file", on Codex this is **`AGENTS.md`** at the project root. Codex also reads `~/.codex/AGENTS.md` for global context. If it finds `AGENTS.override.md` in the project tree or `~/.codex/`, that file takes precedence. Codex reads `AGENTS.md` files from the project root down to the working directory. It appends the contents up to `project_doc_max_bytes` (32 KiB by default).

## Personal skills directory

User-level skills live at **`$CODEX_HOME/skills/`** (default `~/.codex/skills/`). Codex also reads **`~/.agents/skills/`**, which Copilot CLI and Gemini CLI share. If the two paths exist at the same scope, Codex loads the two catalogs. The docs give no precedence rule. Each skill has a `SKILL.md` with `name` and `description` frontmatter.

## Subagent dispatch requires multi-agent support

Add to your Codex config (`~/.codex/config.toml`):

```toml
[features]
multi_agent = true
```

This enables `spawn_agent`, `wait_agent`, and `close_agent` for skills like `superpowers:dispatching-parallel-agents` and `superpowers:subagent-driven-development`.

Legacy note: Codex builds before `rust-v0.115.0` exposed spawned-agent
waiting as `wait`. Current Codex uses `wait_agent` for spawned agents.

The `wait` name belongs to code-mode `exec/wait`, which resumes a yielded exec
cell by `cell_id`. It is not the spawned-agent result tool.

## Environment Detection

Skills that create worktrees or finish branches should find their
environment with read-only git commands before proceeding:

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

- `GIT_DIR != GIT_COMMON` → in a linked worktree (skip setup)
- `BRANCH` empty → detached HEAD (cannot branch/push/PR from sandbox)

See `superpowers:using-git-worktrees` Step 0 and `superpowers:finishing-a-development-branch`
Step 1 for how each skill uses these signals.

## Codex App Finishing

When the sandbox blocks branch/push operations (detached HEAD in an
externally managed worktree), the agent commits all work and informs
the user to use the App's native controls:

- **"Create branch"** — names the branch, then commit/push/PR through App UI
- **"Hand off to local"** — moves work to the user's local checkout

The agent can run tests, add files to the Git index, and output suggested branch
names, commit messages, and PR descriptions for the user to copy.
