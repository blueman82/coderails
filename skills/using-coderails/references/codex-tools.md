# Codex Tool Mapping

Skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). On Codex these resolve to the tools below.

| Action skills request | Codex equivalent |
|----------------------|------------------|
| Read a file | `exec_command` with `cat`, `head`, or `tail` |
| Create / edit / delete a file | `apply_patch` (structured diff for create, update, delete) |
| Run a shell command | `exec_command` |
| Search file contents | `exec_command` with `rg` |
| Find files by name | `exec_command` with `rg --files` or `find` |
| Fetch a URL | the available web tool, or `exec_command` with `curl` when appropriate |
| Search the web | `web_search` (enabled by default; configurable in `config.toml` via the top-level `web_search` setting — `live`, `cached`, or `disabled`) |
| Invoke a skill | Skills load natively — just follow the instructions |
| Dispatch a subagent (a skill naming an agent, e.g. `coderails:loop-worker`) | `spawn_agent` (see [Subagent dispatch requires multi-agent support](#subagent-dispatch-requires-multi-agent-support)) |
| Multiple parallel dispatches | Multiple `spawn_agent` calls in one response |
| Wait for subagent result | `wait_agent` |
| Free up a subagent slot | Wait for the agent to finish; this tool surface has no `close_agent` |
| Task tracking ("create a todo", "mark complete") | `update_plan` |

## Instructions file

On Codex, "your instructions file" means **`AGENTS.md`** at the project root. Codex also reads `~/.codex/AGENTS.md` for global context. An `AGENTS.override.md` in the project tree or `~/.codex/` takes precedence. Codex loads `AGENTS.md` files from the project root down to the current directory. The default `project_doc_max_bytes` limit is 32 KiB.

## Personal skills directory

User-level skills live at **`$CODEX_HOME/skills/`** (default `~/.codex/skills/`). Codex also reads **`~/.agents/skills/`**, which Copilot CLI and Gemini CLI share. If both paths exist at the same scope, Codex loads both catalogs. Its docs do not state a precedence. Each skill has a `SKILL.md` with `name` and `description` frontmatter.

## Subagent dispatch requires multi-agent support

Add to your Codex config (`~/.codex/config.toml`):

```toml
[features]
multi_agent = true
```

This enables `spawn_agent` and `wait_agent` for skills such as `superpowers:dispatching-parallel-agents` and `superpowers:subagent-driven-development`. The current collaboration surface has no `close_agent`; a completed agent frees its slot.

Legacy note: Codex builds before `rust-v0.115.0` exposed spawned-agent
waiting as `wait`. Current Codex uses `wait_agent` for spawned agents. The
`wait` name now belongs to code-mode `exec/wait`, which resumes a yielded exec
cell by `cell_id`; it is not the spawned-agent result tool.

## Environment Detection

Skills that create worktrees or finish branches should detect their
environment with read-only git commands before proceeding:

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

- `GIT_DIR != GIT_COMMON` → already in a linked worktree (skip creation)
- `BRANCH` empty → detached HEAD (cannot branch/push/PR from sandbox)

See `superpowers:using-git-worktrees` Step 0 and `superpowers:finishing-a-development-branch`
Step 1 for how each skill uses these signals.

## Codex App Finishing

When the sandbox blocks branch/push operations (detached HEAD in an
externally managed worktree), the agent commits all work and informs
the user to use the App's native controls:

- **"Create branch"** — names the branch, then commit/push/PR via App UI
- **"Hand off to local"** — transfers work to the user's local checkout

The agent can still run tests, stage files, and output suggested branch
names, commit messages, and PR descriptions for the user to copy.
