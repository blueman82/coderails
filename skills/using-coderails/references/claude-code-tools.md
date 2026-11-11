# Claude Code Tool Mapping

Skills speak in steps ("dispatch a subagent", "create a todo", "read a file"). On Claude Code these resolve to the tools below.

## Tools

| Skill instruction | Claude Code tool |
|----------------------|------------------|
| Read a file | `Read` |
| Make a new file | `Write` |
| Edit a file | `Edit` |
| Run a shell command | `Bash` |
| Find text in files | `Grep` |
| Find files by name | `Glob` |
| Fetch a URL | `WebFetch` |
| Find information on the web | `WebSearch` |
| Invoke a skill | `Skill` |
| Start a subagent (a skill names an agent, e.g. `coderails:loop-worker`) | `Agent` (older releases named this `Task`) |
| Multiple parallel dispatches | Multiple `Agent` calls in one response |
| Task tracking ("create a todo", "mark complete") | `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`. Use `TodoWrite` in `claude -p` or the Agent SDK unless you set `CLAUDE_CODE_ENABLE_TASKS=1`. |
| Background-process / subagent lifecycle (read output, cancel) | `TaskOutput`, `TaskStop` — these are different from the todo tools above and apply to active shells, agents, and remote sessions |

## Instructions file

On Claude Code, "your instructions file" means **`CLAUDE.md`**. Claude Code goes up the directory tree from the current directory. It reads the `CLAUDE.md` and `CLAUDE.local.md` files it finds as a single set of instructions. Standard locations are:

| Scope | Location |
|-------|----------|
| Project (team-shared) | `./CLAUDE.md` or `./.claude/CLAUDE.md` |
| User global | `~/.claude/CLAUDE.md` |
| Local-private (gitignored) | `./CLAUDE.local.md` |
| Managed policy (org-wide) | `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS), `/etc/claude-code/CLAUDE.md` (Linux/WSL), `C:\Program Files\ClaudeCode\CLAUDE.md` (Windows) |

CLAUDE.md files can pull in more content with `@path/to/file` imports (relative or absolute, max five hops deep). When Claude Code reads files in a subdirectory, it automatically loads the `CLAUDE.md` file there.

Claude Code does **not** read `AGENTS.md` directly. If a project uses `AGENTS.md` for other agents, import it from `CLAUDE.md`. The runtimes then read the same instructions:

```markdown
@AGENTS.md

## Claude Code

(Claude-Code-specific instructions go here.)
```

For path-scoped rules and larger-project organization, see `.claude/rules/` (rules can be scoped to specified files through `paths` frontmatter and load on demand).

## Personal skills directory

User-level skills live at **`~/.claude/skills/`**. Each skill has a `SKILL.md` with `name` and `description` frontmatter. It can have more files. Claude Code does not currently read the cross-runtime `~/.agents/skills/` path. Codex, Copilot CLI, and Gemini CLI do. Check the [official skills docs](https://code.claude.com/docs/en/skills) for updates on this feature.
