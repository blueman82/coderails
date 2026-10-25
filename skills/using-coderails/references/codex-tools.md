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
| Search the web | Use the web-search tool exposed by the current Codex host. Its name and availability can differ by host. |
| Invoke a skill | Skills load natively — just follow the instructions |
| Dispatch a subagent (a skill naming an agent, e.g. `coderails:loop-worker`) | `spawn_agent` (see [Subagent dispatch requires multi-agent support](#subagent-dispatch-requires-multi-agent-support)) |
| Multiple parallel dispatches | Multiple `spawn_agent` calls in one response |
| Wait for subagent result | `wait_agent` |
| Free up a subagent slot | Wait for the agent to finish; this tool surface has no `close_agent` |
| Task tracking ("create a todo", "mark complete") | Use a plan tool when the host exposes one. Otherwise keep a concise checklist in the session or an approved work file. |

## Instructions file

On Codex, project instructions commonly come from **`AGENTS.md`** at the
project root and applicable nested paths. A host can also supply an
`AGENTS.md` block in the user input. Global instructions may come from
`~/.codex/AGENTS.md`; an applicable `AGENTS.override.md` takes precedence.
Check the instruction sources presented in this session. A host can cap
the bytes it loads from project files.

## Personal skills directory

User-level skills live at **`$CODEX_HOME/skills/`** (default `~/.codex/skills/`). Codex also reads **`~/.agents/skills/`**, which Copilot CLI and Gemini CLI share. If both paths exist at the same scope, Codex loads both catalogs. Its docs do not state a precedence. Each skill has a `SKILL.md` with `name` and `description` frontmatter.

## Subagent dispatch requires multi-agent support

Before a skill delegates, check whether this session exposes `spawn_agent`
and `wait_agent`. Multi-agent support is set by the host at session start;
do not assume a repository skill can enable it. If the tools are absent,
use the host's documented setup or keep dependent work in the main session.
The current collaboration surface has no `close_agent`; a completed agent
frees its slot.

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
