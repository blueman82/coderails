# Codex Tool Mapping

Skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). On Codex these resolve to the tools below.

| Action skills request | Codex equivalent |
|----------------------|------------------|
| Read a file | `exec_command` with `cat`, `sed`, `head`, or `tail` |
| Create / edit / delete a file | `apply_patch` (structured diff for create, update, delete) |
| Run a shell command | `exec_command` |
| Search file contents | `exec_command` with `rg` |
| Find files by name | `exec_command` with `rg --files` or `find` |
| Fetch a URL | the available web tool, or `exec_command` with `curl` when appropriate |
| Search the web | Use the web tool exposed in this session. The local CLI has `--search` to enable its native `web_search` tool. |
| Invoke a skill | Skills load natively — just follow the instructions |
| Dispatch a subagent (for example the installed `loop-worker`) | `spawn_agent` (see [Subagent dispatch requires multi-agent support](#subagent-dispatch-requires-multi-agent-support)) |
| Multiple parallel dispatches | Multiple `spawn_agent` calls in one response |
| Send context to a running subagent | `send_message` |
| Give an idle subagent another turn | `followup_task` |
| Wait for a subagent update or final status | `wait_agent` |
| Stop a subagent's current turn | `interrupt_agent` |
| Task tracking ("create a todo", "mark complete") | Use `update_plan` when exposed. The observed collaboration surface does not expose it. |

## Instructions file

When a skill mentions "your instructions file", on Codex this is **`AGENTS.md`** at the project root.
Codex also reads `~/.codex/AGENTS.md` for global context, and an `AGENTS.override.md` (in the project tree or `~/.codex/`) takes precedence when present.
Codex walks from the project root down to the current working directory, concatenating `AGENTS.md` files it finds along the way, up to `project_doc_max_bytes` (32 KiB by default).

## Personal skills directory

User-level skills live at **`$CODEX_HOME/skills/`** (default `~/.codex/skills/`).
Codex also reads the cross-runtime path **`~/.agents/skills/`** (shared with Copilot CLI and Gemini CLI).
When both directories exist at the same scope, Codex loads them both as separate skill catalogs — Codex's docs don't currently document a precedence between them.
Each skill is a subdirectory containing a `SKILL.md` (with `name` and `description` frontmatter).

## Subagent dispatch requires multi-agent support

Add to your Codex config (`~/.codex/config.toml`):

```toml
[features]
multi_agent = true
```

Multi-agent support exposes the collaboration tools available in the active
session. On the surface observed on 2026-10-24, these are `spawn_agent`,
`send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and
`list_agents`. There is no `close_agent` tool. A final status ends the
subagent's turn; stop waiting when that status arrives. `interrupt_agent`
stops a current turn but does not retire the agent. The local CLI reports
`codex-cli 0.164.0`; the session tool surface is the authority for tool names.
The local `codex --help` lists `--search`; it does not establish that search
is enabled in every session.

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

Use these signals before creating a worktree or finishing a branch.

## Codex App Finishing

When the sandbox blocks branch/push operations (detached HEAD in an
externally managed worktree), the agent commits all work and informs
the user to use the App's native controls:

- **"Create branch"** — names the branch, then commit/push/PR via App UI
- **"Hand off to local"** — transfers work to the user's local checkout

The agent can still run tests, stage files, and output suggested branch
names, commit messages, and PR descriptions for the user to copy.
