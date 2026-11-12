# Gemini CLI Tool Mapping

Skills speak in steps ("dispatch a subagent", "create a todo", "read a file"). On Gemini CLI these resolve to the tools below.

| Skill instruction | Gemini CLI equivalent |
|----------------------|----------------------|
| Read a file | `read_file` |
| Read multiple files at the same time | `read_many_files` |
| Make a new file | `write_file` |
| Edit a file | `replace` |
| Run a shell command | `run_shell_command` |
| Find text in files | `grep_search` |
| Find files by name | `glob` |
| List files and subdirectories | `list_directory` |
| Fetch a URL | `web_fetch` |
| Find information on the web | `google_web_search` |
| Invoke a skill | `activate_skill` |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | `invoke_agent` with `agent_name: "generalist"` (invocable through `@generalist` chat syntax — see [Subagent tools](#subagent-support)) |
| Multiple parallel dispatches | Multiple `invoke_agent` calls in the same response |
| Task tracking ("create a todo", "mark complete") | `write_todos` (statuses: pending, in_progress, completed, cancelled, blocked) |

## Instructions file

When a skill mentions "your instructions file", on Gemini CLI this is **`GEMINI.md`**. Gemini CLI reads `GEMINI.md` files in workspace directories and their ancestors. It also reads the global `~/.gemini/GEMINI.md`. If a tool reads a file in a subdirectory, Gemini CLI also reads the subdirectory's `GEMINI.md`.

## Personal skills directory

User-level skills live at **`~/.gemini/skills/`**. The cross-runtime alias **`~/.agents/skills/`** is shared with Codex and Copilot CLI. If the two paths exist at the same scope, `.agents/skills/` takes precedence. Each skill has a `SKILL.md` with `name` and `description` frontmatter.

## Subagent support

Gemini CLI dispatches subagents through the `invoke_agent` tool, which takes `agent_name` and `prompt` parameters. The same dispatch is also surfaced as a chat-syntax shortcut: typing `@generalist <prompt>` does the same as `invoke_agent` with `agent_name: "generalist"`. Built-in agent names include `generalist`, `cli_help`, `codebase_investigator`, and (with browser tooling enabled) `browser_agent`.

Skills name an agent such as `coderails:loop-worker` or `pr-review-toolkit:code-reviewer`, or supply an inline prompt. Gemini CLI has no equivalent of a named agent definition. Read the agent file and include its instructions in the prompt.

| Skill instruction | Gemini CLI equivalent |
|---------------------|----------------------|
| Names an implementer agent (`coderails:loop-worker`) | Read the agent file, then `invoke_agent` with `agent_name: "generalist"` and its body as the prompt prefix |
| Names a reviewer agent (`pr-review-toolkit:code-reviewer`, `coderails:spec-reviewer`, `coderails:source-auditor`) | Use the same steps. Specify read-only access in the prompt because `generalist` has write tools. |
| Inline prompt (no agent named) | `invoke_agent` with `agent_name: "generalist"` and your inline prompt |

Claude Code enforces read-only access for some agents:
only `coderails:spec-reviewer` truly withholds write tools through its `tools:` list.
`coderails:source-auditor` disallows `Write`/`Edit` but keeps `Bash`, and
`pr-review-toolkit:code-reviewer` declares no `tools:` key at all, so it has full
access.

On Gemini CLI the tool cannot limit access to read-only operations. Specify the
read-only constraint explicitly in the prompt for each reviewer or auditor.

### Prompt filling

Skills provide prompt templates with placeholders like `{WHAT_WAS_IMPLEMENTED}` or `[FULL TEXT of task]`. Fill all placeholders before passing the complete prompt to `invoke_agent`. The prompt template gives the agent its role, criteria for its checks, and expected output format. The subagent follows the template.

### Parallel dispatch

Gemini CLI can start subagents in parallel. Put `invoke_agent` calls without dependencies in one response, or use multiple `@generalist` invocations in one prompt. Run dependent tasks in sequence.

## Additional Gemini CLI tools

These tools are unique to Gemini CLI:

| Tool | Purpose |
|------|---------|
| `save_memory` (legacy) | Keep facts across sessions when `experimental.memoryV2 = false` |
| `get_internal_docs` | Look up Gemini CLI's bundled documentation |
| `ask_user` | Pose structured questions to the user (text / single-select / multi-select) |
| `enter_plan_mode` / `exit_plan_mode` | Start or stop read-only plan mode |
| `update_topic` | Update the current conversation's topic / strategic-intent metadata |
| `complete_task` | Signal that a Gemini subagent has completed and give its result to the parent agent |
| `tracker_create_task`, `tracker_update_task`, `tracker_get_task`, `tracker_list_tasks`, `tracker_add_dependency`, `tracker_visualize` | Task tracker with dependency lists and diagrams |
| `read_mcp_resource`, `list_mcp_resources` | MCP resource access |
