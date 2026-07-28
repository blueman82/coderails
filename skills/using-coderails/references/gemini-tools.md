# Gemini CLI Tool Mapping

Skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). On Gemini CLI these resolve to the tools below.

| Action skills request | Gemini CLI equivalent |
|----------------------|----------------------|
| Read a file | `read_file` |
| Read multiple files at once | `read_many_files` |
| Create a new file | `write_file` |
| Edit a file | `replace` |
| Run a shell command | `run_shell_command` |
| Search file contents | `grep_search` |
| Find files by name | `glob` |
| List files and subdirectories | `list_directory` |
| Fetch a URL | `web_fetch` |
| Search the web | `google_web_search` |
| Invoke a skill | `activate_skill` |
| Dispatch a subagent (a skill naming an agent, e.g. `coderails:loop-worker`) | `invoke_agent` with `agent_name: "generalist"` (invocable via `@generalist` chat syntax — see [Subagent support](#subagent-support)) |
| Multiple parallel dispatches | Multiple `invoke_agent` calls in the same response |
| Task tracking ("create a todo", "mark complete") | `write_todos` (statuses: pending, in_progress, completed, cancelled, blocked) |

## Instructions file

When a skill mentions "your instructions file", on Gemini CLI this is **`GEMINI.md`**. Gemini CLI loads `GEMINI.md` hierarchically: global at `~/.gemini/GEMINI.md`, project-level files in workspace directories and their ancestors, and sub-directory `GEMINI.md` files when a tool accesses files in those directories.

## Personal skills directory

User-level skills live at **`~/.gemini/skills/`**, with **`~/.agents/skills/`** as a cross-runtime alias (shared with Codex and Copilot CLI). When both directories exist at the same scope, `.agents/skills/` takes precedence. Each skill is a subdirectory containing a `SKILL.md` (with `name` and `description` frontmatter).

## Subagent support

Gemini CLI dispatches subagents through the `invoke_agent` tool, which takes `agent_name` and `prompt` parameters. The same dispatch is also surfaced as a chat-syntax shortcut: typing `@generalist <prompt>` is equivalent to calling `invoke_agent` with `agent_name: "generalist"`. Built-in agent names include `generalist`, `cli_help`, `codebase_investigator`, and (with browser tooling enabled) `browser_agent`.

Skills dispatch by naming an agent (e.g. `coderails:loop-worker`,
`pr-review-toolkit:code-reviewer`) or by supplying an inline prompt. Gemini CLI
has no equivalent of a named agent definition, so the agent's own system prompt
does not come along — read the agent file and carry its instructions into the
prompt yourself. On Gemini CLI:

| Skill dispatch form | Gemini CLI equivalent |
|---------------------|----------------------|
| Names an implementer agent (`coderails:loop-worker`) | Read the agent file, then `invoke_agent` with `agent_name: "generalist"` and its body as the prompt prefix |
| Names a reviewer agent (`pr-review-toolkit:code-reviewer`, `coderails:spec-reviewer`, `coderails:source-auditor`) | Same, but state the read-only constraint explicitly in the prompt — `generalist` still has write tools |
| Inline prompt (no agent named) | `invoke_agent` with `agent_name: "generalist"` and your inline prompt |

The read-only note matters, and the Claude Code side is weaker than it looks:
only `coderails:spec-reviewer` truly withholds write tools via its `tools:` list.
`coderails:source-auditor` disallows `Write`/`Edit` but keeps `Bash`, and
`pr-review-toolkit:code-reviewer` declares no `tools:` key at all, so it has full
access. On Gemini CLI there is no tool-level enforcement either way, so state the
read-only constraint explicitly in the prompt for every reviewer or auditor.

### Prompt filling

Skills provide prompt templates with placeholders like `{WHAT_WAS_IMPLEMENTED}` or `[FULL TEXT of task]`. Fill all placeholders before passing the complete prompt to `invoke_agent`. The prompt template itself contains the agent's role, review criteria, and expected output format — the subagent will follow it.

### Parallel dispatch

Gemini CLI supports parallel subagent dispatch. Issue multiple `invoke_agent` calls in the same response (or multiple `@generalist` invocations in one prompt) to run independent subagent work in parallel. Keep dependent tasks sequential, but do not serialize independent subagent tasks just to preserve a simpler history.

## Additional Gemini CLI tools

These tools are unique to Gemini CLI:

| Tool | Purpose |
|------|---------|
| `save_memory` (legacy) | Persist facts across sessions when `experimental.memoryV2 = false` |
| `get_internal_docs` | Look up Gemini CLI's bundled documentation |
| `ask_user` | Pose structured questions to the user (text / single-select / multi-select) |
| `enter_plan_mode` / `exit_plan_mode` | Switch into and out of read-only plan mode |
| `update_topic` | Update the current conversation's topic / strategic-intent metadata |
| `complete_task` | Signal that a Gemini subagent has completed and return its result to the parent agent |
| `tracker_create_task`, `tracker_update_task`, `tracker_get_task`, `tracker_list_tasks`, `tracker_add_dependency`, `tracker_visualize` | Rich task tracker with dependency and visualization support |
| `read_mcp_resource`, `list_mcp_resources` | MCP resource access |
