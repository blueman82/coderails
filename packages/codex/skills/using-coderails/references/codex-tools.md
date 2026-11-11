# Codex Tool Mapping

Skills give instructions ("dispatch a subagent", "create a todo", "read a file"). Use these tools in Codex.

| Step in the skill | Codex equivalent |
|----------------------|------------------|
| Read a file | `exec_command` with `cat`, `sed`, `head`, or `tail` |
| Make / edit / delete a file | `apply_patch` (structured diff for make, update, delete) |
| Run a shell command | `exec_command` |
| Examine file contents | `exec_command` with `rg` |
| Find files by name | `exec_command` with `rg --files` or `find` |
| Fetch a URL | the available web tool, or `exec_command` with `curl` when applicable |
| Look up web content | `web_search` is on by default. The top-level `web_search` setting in `config.toml` accepts `live`, `cached`, or `disabled`. |
| Invoke a skill | Skills load natively. Follow the instructions. |
| Start a subagent (for example the installed `loop-worker`) | `spawn_agent`. See [the multi-agent setting](#subagent-dispatch-requires-multi-agent-support). |
| Multiple parallel dispatches | Multiple `spawn_agent` calls in one response |
| Send a correction or instructions to continue to an active subagent | `send_input` |
| Wait for subagent result | `wait_agent` |
| Free up subagent slot when done | `close_agent` |
| Task tracking ("create a todo", "mark complete") | `update_plan` |

## Instructions file

When a skill mentions "your instructions file", on Codex this is **`AGENTS.md`** at the project root.
Codex also reads `~/.codex/AGENTS.md` for global context. If it finds an `AGENTS.override.md` in the project tree or `~/.codex/`, that file takes precedence.
Codex walks from the project root down to the current working directory and joins the `AGENTS.md` files it finds.
The limit is `project_doc_max_bytes` (32 KiB by default).

## Personal skills directory

User-level skills live at **`$CODEX_HOME/skills/`** (default `~/.codex/skills/`).
Codex also reads the cross-runtime path **`~/.agents/skills/`** (shared with Copilot CLI and Gemini CLI).
If the two directories exist at the same scope, Codex loads one skill catalog from each.
Codex's docs do not currently specify precedence between them.
Each skill is a subdirectory containing a `SKILL.md` (with `name` and `description` frontmatter).

## Subagent dispatch requires multi-agent support

Add to your Codex config (`~/.codex/config.toml`):

```toml
[features]
multi_agent = true
```

This enables `spawn_agent`, `send_input`, `wait_agent`, and `close_agent`.

Legacy note: Codex builds before `rust-v0.115.0` used `wait` to wait for spawned agents.
Current Codex uses `wait_agent` for spawned agents.

The `wait` name belongs to code-mode `exec/wait`, which resumes a yielded exec cell by `cell_id`.
It is not the spawned-agent result tool.

## Environment Detection

Skills that create worktrees or finish branches should find their
environment with read-only git commands before proceeding:

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

- `GIT_DIR != GIT_COMMON` → in a linked worktree (skip creation)
- `BRANCH` empty → detached HEAD (cannot branch/push/PR from sandbox)

Use these signals before creating a worktree or finishing a branch.

## Codex App Finishing

When the sandbox blocks branch/push operations (detached HEAD in an
externally managed worktree), the agent commits all work and informs
the user to use the App's native controls:

- **"Create branch"** — names the branch, then commit/push/PR through App UI
- **"Hand off to local"** — moves work to the user's local checkout

The agent can run tests, add files to the Git index, and output suggested branch
names, commit messages, and PR descriptions for the user to copy.
