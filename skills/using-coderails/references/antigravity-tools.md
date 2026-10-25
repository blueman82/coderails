# Antigravity CLI (`agy`) Tool Mapping

Skills name actions such as dispatching an agent or reading a file. On the
Antigravity CLI (`agy`), use these tools:

| Action skills request | Antigravity CLI equivalent |
|----------------------|----------------------|
| Read a file | `view_file` |
| Create a new file | `write_to_file` |
| Edit a file | `replace_file_content` |
| Edit a file in several places at once | `multi_replace_file_content` |
| Run a shell command | `run_command` |
| Search file contents | `grep_search` |
| Find files by name / list a directory | `list_dir` (no dedicated glob tool — combine `list_dir` with `grep_search`) |
| Fetch a URL | `read_url_content` |
| Search the web | `search_web` |
| Pose a structured question to your human partner | `ask_question` |
| Dispatch a subagent (a skill naming an agent, e.g. `coderails:loop-worker`) | `invoke_subagent` with an installed custom role when its tool policy fits; `self` is full-capability, while `research` is optimized for research without a documented read-only guarantee (see [Subagent support](#subagent-support)) |
| Multiple parallel dispatches | Multiple entries in one `invoke_subagent` call's `Subagents` array |
| Task tracking ("create a todo", "mark complete") | a **task artifact** — `write_to_file` with `IsArtifact: true` and `ArtifactMetadata.ArtifactType: "task"` (see [Task tracking](#task-tracking)). **Not** `manage_task`, which manages background processes. |

## Invoking a skill — read its `SKILL.md`

Antigravity shows each installed skill's `name` and `description` at the start
of a session. It has no `Skill` or `activate_skill` tool.

When a skill applies, read its `SKILL.md` with `view_file`. Set
`IsSkillFile: true`. For example, read
`.../plugins/coderails/skills/<skill-name>/SKILL.md` with that setting.
`IsSkillFile` tells Antigravity that you intend to use the skill's instructions.

This is Antigravity's way to load a skill. Read the applicable `SKILL.md`
with `IsSkillFile: true` before you act.

## Subagent support

Antigravity dispatches subagents with `invoke_subagent`. Put a `TypeName` for
each worker in the `Subagents` array. Two types are built in. You can use them
without `define_subagent`:

- **`self`** — a full clone of you, with every tool you have (including
  `write_to_file`/`replace_file_content`/`run_command`). The safe default for
  general-purpose work: implementing, fixing, anything that edits files or runs
  commands.
- **`research`** — optimized for codebase research, file navigation, and
  structural exploration. The [provider subagent guide](https://www.agy.dev/docs/subagents?tab=cli)
  does not promise a read-only tool set. Do not use this type alone as proof
  that a reviewer cannot edit files or run commands.

Use `define_subagent` only when you need a custom system prompt or capability
mix. Set `enable_write_tools: true` to grant file edits and `run_command`.
Set `enable_subagent_tools` for nested dispatch, and `enable_mcp_tools` for
MCP. Then invoke the type by the name you gave it. `manage_subagents` lists
or stops running subagents.

Skills dispatch by naming an agent (e.g. `coderails:loop-worker`,
`pr-review-toolkit:code-reviewer`) or by supplying an inline prompt.
Antigravity can discover Markdown custom-agent definitions in a plugin's
`agents/` directory, a workspace `.agents/agents/` directory, or its global
agent directory. Their Markdown bodies become system prompts. Check that
the named role is installed and that its tool policy fits the task. If the
role is unavailable, use a built-in type and carry the role instructions
explicitly in the prompt. See the [Antigravity custom-agent guide](https://www.agy.dev/docs/subagents?tab=cli).

When no installed custom role fits:

| Skill dispatch form | Antigravity equivalent |
|---------------------|----------------------|
| An implementer agent (`coderails:loop-worker`) — writes code, runs tests | Read the agent file, then `invoke_subagent` with `TypeName: "self"` and its body as the prompt prefix |
| A read-only agent (`pr-review-toolkit:code-reviewer`, `coderails:spec-reviewer`, `coderails:source-auditor`) | Use an installed custom role with an explicit read-only `tools` allowlist; if none is available, report that the required tool boundary is unverified |
| Inline prompt (no agent named) | `invoke_subagent` with `TypeName: "self"` for general work; `research` can help with investigation when a hard read-only boundary is not required |

An installed custom agent can declare a `tools` allowlist in its Markdown
frontmatter. Inspect that list before a review that requires read-only
tools. The built-in `research` type has no documented read-only guarantee;
its name and prompt are not proof of a tool boundary.

### Prompt filling

Skills provide prompt templates with placeholders like `{WHAT_WAS_IMPLEMENTED}` or
`[FULL TEXT of task]`. Fill all placeholders before passing the complete prompt to
`invoke_subagent`. The prompt template itself contains the agent's role, review
criteria, and expected output format — the subagent will follow it.

### Parallel dispatch

Put multiple entries in a single `invoke_subagent` call's `Subagents` array to run
independent subagent work in parallel. Keep dependent tasks sequential, but do not
serialize independent subagent tasks just to preserve a simpler history.

## Task tracking

Antigravity has **no todo / `TodoWrite` tool** (`manage_task` manages background
processes — `list`/`kill`/`status`/`send_input` — it is *not* a checklist). When a
skill says to create a todo list or track tasks, maintain a **task artifact**: a
markdown checklist saved with `write_to_file` (`IsArtifact: true`,
`ArtifactMetadata.ArtifactType: "task"`), edited with `replace_file_content` /
`multi_replace_file_content` as you go.

At the start of any multi-step task, create the task artifact listing every step of
your plan. As you complete each step, edit the artifact to mark it done (`- [x]`).
If the plan changes, update the checklist. Keep it current — it is your source of
truth for what remains; once the conversation gets long, re-read it before starting
each step.
