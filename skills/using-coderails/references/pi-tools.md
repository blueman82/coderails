# Pi Tool Mapping

Skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). On Pi these resolve to the tools below.

| Action skills request | Pi equivalent |
| --- | --- |
| Invoke a skill | Pi native skills: load the relevant `SKILL.md` with `read`, or let the human use `/skill:name` |
| Read a file | `read` |
| Create a file | `write` |
| Edit a file | `edit` |
| Run a shell command | `bash` |
| Search file contents | `grep` when active; otherwise `bash` with `rg`/`grep` |
| Find files by name | `find` or `bash` with shell globs |
| List files and subdirectories | `ls` when active; otherwise `bash` with `ls` |
| Dispatch a subagent (a skill naming an agent, e.g. `coderails:loop-worker`) | Use an installed subagent tool such as `subagent` from `pi-subagents` if available |
| Task tracking ("create a todo", "mark complete") | Use an installed todo/task tool if available, otherwise track tasks in the plan or `TODO.md` |

## Skills

Pi finds skills in configured directories and installed packages. A Coderails plugin should expose `skills/` through `pi.skills` in its manifest. Pi has no Claude Code `Skill` tool. When a skill applies, load and follow it before responding.

## Subagents

Pi core has no standard subagent tool. The optional `pi-subagents` package adds a `subagent` tool. It supports single-agent, chain, parallel, async, forked-context, and resume/status work. If it is unavailable, work in sequence or explain that the optional capability is missing. Do not invent `Task` calls.

## Task lists

Pi core has no standard task-list tool. Use an installed task extension if one exists. Otherwise, use a Coderails plan, a Markdown checklist, or a repo-local `TODO.md`. Older Coderails docs may say `TodoWrite`; treat it as this task-tracking action.
