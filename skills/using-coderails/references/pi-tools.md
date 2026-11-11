# Pi Tool Mapping

Skills speak in steps ("dispatch a subagent", "create a todo", "read a file"). On Pi these resolve to the tools below.

| Skill instruction | Pi equivalent |
| --- | --- |
| Invoke a skill | Pi native skills: load the related `SKILL.md` with `read`, or let the human use `/skill:name` |
| Read a file | `read` |
| Make a file | `write` |
| Edit a file | `edit` |
| Run a shell command | `bash` |
| Find text in files | `grep` when active. If not, use `bash` with `rg` or `grep`. |
| Find files by name | `find` or `bash` with shell globs |
| List files and subdirectories | `ls` when active. If not, use `bash` with `ls`. |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | Use an installed subagent tool such as `subagent` from `pi-subagents` if available |
| Task tracking ("create a todo", "mark complete") | Use an installed todo/task tool if available. If not, monitor tasks in the plan or `TODO.md` |

## Skills

Pi finds skills in configured directories and installed packages. A Coderails plugin should list `skills/` in the manifest field `pi.skills`. Pi has no Claude Code `Skill` tool. When a skill applies, load and follow it before responding.

## Subagents

Pi core has no standard subagent tool. The optional `pi-subagents` package adds a `subagent` tool. Use it for single agents, chains, parallel or async work, forked contexts, and resume or status operations. If it is unavailable, work in sequence or explain that you do not have this tool. Do not invent `Task` calls.

## Task lists

Pi core has no standard task-list tool. Use an installed task extension's documented tool if one exists. If not, use a Coderails plan, a Markdown checklist, or a repo-local `TODO.md`. Older Coderails docs may say `TodoWrite`. Use it for this task-tracking step.
