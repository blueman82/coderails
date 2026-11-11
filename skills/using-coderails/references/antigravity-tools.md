# Antigravity CLI (`agy`) Tool Mapping

Skills tell you to start agents, read files, and do other work. On Antigravity CLI (`agy`), use these tools.

| Skill instruction | Antigravity CLI equivalent |
|----------------------|----------------------|
| Read a file | `view_file` |
| Make a new file | `write_to_file` |
| Edit a file | `replace_file_content` |
| Edit multiple parts of a file in one operation | `multi_replace_file_content` |
| Run a shell command | `run_command` |
| Find text in files | `grep_search` |
| Find files by name / list a directory | `list_dir` (no dedicated glob tool — combine `list_dir` with `grep_search`) |
| Fetch a URL | `read_url_content` |
| Find information on the web | `search_web` |
| Pose a structured question to your human partner | `ask_question` |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | `invoke_subagent` with a built-in `TypeName` — `self` for full-capability work, `research` for read-only (see [Subagent types](#subagent-support)) |
| Multiple parallel dispatches | Multiple entries in one `invoke_subagent` call's `Subagents` array |
| Task tracking ("create a todo", "mark complete") | a **task artifact** — `write_to_file` with `IsArtifact: true` and `ArtifactType: "task"` (see [Task tracking](#task-tracking)). Use `manage_task` only for background commands. |

## Invoking a skill — read its `SKILL.md`

At session start, Antigravity shows the `name` and `description` of each installed skill. It has no `Skill` or `activate_skill` tool. If the skill applies, **read its `SKILL.md` with `view_file` and set `IsSkillFile: true`**.

For example, use `view_file` on `.../plugins/coderails/skills/<skill-name>/SKILL.md` with `IsSkillFile: true`. This tells Antigravity to follow the instructions in the file. Set it each time you invoke a skill, not when you edit or preview it.

The general rule "never read skill files manually" means "do not bypass your platform's skill-loading mechanism". On Antigravity, use `SKILL.md` as described above to follow that rule.

Use the names and descriptions shown at session start to find applicable skills. Before you start the task, read the applicable skill's `SKILL.md`.

## Subagent support

Antigravity dispatches subagents with `invoke_subagent`, passing each one a
`TypeName` in the `Subagents` array. Two `TypeName`s are **built in** — use them
directly, no `define_subagent` needed:

- **`self`** — has all your tools, such as `write_to_file`, `replace_file_content`, and `run_command`. Use it by default for general work, file edits, and commands.
- **`research`** — can read files, use `grep_search`, and fetch web pages or URLs. It cannot write files or run commands. Use it for investigation and read-only checks.

Use `define_subagent` only if the task requires a custom system prompt or a custom set of tools. Set `enable_write_tools: true` to grant file edits and `run_command`.
Set `enable_subagent_tools` for nested dispatch, and `enable_mcp_tools` for
MCP. Then invoke the type by the name you gave it.

`manage_subagents` lists or stops active subagents.

Skills name an agent such as `coderails:loop-worker` or `pr-review-toolkit:code-reviewer`, or supply an inline prompt. Antigravity has no equivalent of a named agent definition. Read the agent file and include its body in the prompt.

| Skill instruction | Antigravity equivalent |
|---------------------|----------------------|
| An implementer agent (`coderails:loop-worker`) — writes code, runs tests | Read the agent file, then `invoke_subagent` with `TypeName: "self"` and its body as the prompt prefix |
| A read-only agent (`pr-review-toolkit:code-reviewer`, `coderails:spec-reviewer`, `coderails:source-auditor`) | `invoke_subagent` with `TypeName: "research"` and the agent's body as the prompt prefix |
| Inline prompt (no agent named) | `invoke_subagent` with `TypeName: "self"` (or `"research"` if the task only reads) and your inline prompt |

Use `TypeName: "research"` for each reviewer and auditor. This provides read-only access like a read-only `tools:` list. The runtime limits the tools to read-only operations.

### Prompt filling

Skills provide prompt templates with placeholders like `{WHAT_WAS_IMPLEMENTED}` or
`[FULL TEXT of task]`. Fill all placeholders before passing the complete prompt to
`invoke_subagent`. The prompt template gives the agent its role, criteria for its checks, and expected output format. The subagent follows the template.

### Parallel dispatch

Put tasks without dependencies in the `Subagents` array of one `invoke_subagent` call. They run in parallel. Run dependent tasks in sequence. Do not put tasks without dependencies in sequence for a simpler history.

## Task tracking

Antigravity has no todo or `TodoWrite` tool. The `manage_task` tool controls background commands with `list`, `kill`, `status`, and `send_input`.

When a skill tells you to keep a todo list or monitor tasks, use a **task artifact**. Write a Markdown checklist with `write_to_file` and set `IsArtifact: true` and `ArtifactMetadata.ArtifactType: "task"`. Update it with `replace_file_content` or `multi_replace_file_content`.

At the start of each multi-step task, make a task artifact that lists all steps of your plan. When you complete a step, mark it done (`- [x]`). If the plan changes, update the checklist.

Use the checklist to see what remains. If the conversation gets long, read the checklist again before you start each step.
