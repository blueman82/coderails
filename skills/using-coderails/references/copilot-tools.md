# Copilot CLI Tool Mapping

Skills speak in steps ("dispatch a subagent", "create a todo", "read a file"). On Copilot CLI these resolve to the tools below.

| Skill instruction | Copilot CLI equivalent |
|----------------------|----------------------|
| Read a file | `view` |
| Make, edit, or remove a file | `apply_patch` (Copilot CLI uses this tool for file operations) |
| Run a shell command | `bash` |
| Find text in files | `rg` (ripgrep). Copilot CLI has no `grep` tool. |
| Find files by name | `glob` |
| Fetch a URL | `web_fetch` |
| Find information on the web | `web_search` |
| Invoke a skill | `skill` |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | `task` with `agent_type: "general-purpose"` (other accepted types: `explore`, `task`, `code-review`, `research`, `configure-copilot`) |
| Multiple parallel dispatches | Multiple `task` calls in one response |
| Subagent status/output/control | `read_agent`, `list_agents`, `write_agent` |
| Task tracking ("create a todo", "mark complete") | `update_todo` |
| Start or stop plan mode | No equivalent — stay in the primary session |

## Instructions file

When a skill mentions "your instructions file", on Copilot CLI this is **`AGENTS.md`** at the repository root. If `AGENTS.md` and `.github/copilot-instructions.md` are available, Copilot reads the two files.

## Personal skills directory

User-level skills live at **`~/.copilot/skills/`**. Copilot CLI also reads **`~/.agents/skills/`**, which Codex and Gemini CLI share. Each skill has a `SKILL.md` with `name` and `description` frontmatter.

## Async shell sessions

Copilot CLI can keep async shell sessions open.

| Tool | Purpose |
|------|---------|
| `bash` with `mode: "async"` (and optionally `detach: true`) | Start a long-running command in the background. The tool gives a `shellId`. |
| `write_bash` | Send input to an active async session |
| `read_bash` | Read output from an async session |
| `stop_bash` | Stop an async session |
| `list_bash` | List all active shell sessions |

## Additional Copilot CLI tools

| Tool | Purpose |
|------|---------|
| `store_memory` | Keep facts about the codebase for future sessions |
| `report_intent` | Update the UI status line with current intent |
| `sql` | Query the session's SQLite database (todos, metadata) |
| `fetch_copilot_cli_documentation` | Look up Copilot CLI documentation |
| GitHub MCP tools (`github-mcp-server-*`) | Native GitHub API access (issues, PRs, code search) |
