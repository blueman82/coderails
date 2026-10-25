#!/usr/bin/env python3
"""Run one guarded role as its own contained Codex session: `codex_role_session.py --role <agent> --prompt-file <f>`.

Codex native children inherit the parent's permissions and MCP servers, and a role TOML's sandbox_mode does not change
that. A separate `codex exec` does: user config is ignored, the sandbox is read-only, shell and nested agents are off,
and exactly one MCP server (this role's, from capability_mcp.py) is registered. The prompt comes from a file, and the
environment is an allowlist. Use it for source-auditor. Its tests_run/cmd_run must not be reachable by native children.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOOLS = {"repo.inspect", "diff.read", "tests.run", "pr.comment", "cmd.run"}
ENV_ALLOW = ("PATH", "HOME", "CODEX_HOME", "LANG", "LC_ALL", "TERM", "TMPDIR")
ROLE = re.compile(r"^[a-z][a-z0-9-]{0,60}$")
OPTIONS = {"--role", "--prompt-file", "--cwd"}
SOURCE_AUDITOR_APPROVALS = (
    'mcp_servers.cap-source-auditor.tools.cmd_run.approval_mode="approve"',
    'mcp_servers.cap-source-auditor.tools.tests_run.approval_mode="approve"',
)


def guarded_roles(root: Path) -> set[str]:
    """Roles with a capability tool and neither raw shell nor write access, from capabilities/profiles.json."""
    try:
        text = (root / "capabilities" / "profiles.json").read_text(encoding="utf-8")
        agents: dict[str, Any] = json.loads(text)["agents"]
        return {
            name
            for name, caps in agents.items()
            if TOOLS & set(caps) and not {"shell.raw", "worktree.write"} & set(caps)
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"capabilities/profiles.json unreadable or malformed: {error}") from error


def project_codex_dir(start: Path) -> Path | None:
    """The first `.codex` directory from start up to and including the repo root (the dir holding `.git`), if any."""
    here = start.resolve()
    for directory in (here, *here.parents):
        if (directory / ".codex").exists():
            return directory / ".codex"
        if (directory / ".git").exists():
            return None
    return None


def role_instructions(root: Path, role: str) -> str:
    """Read the tracked role contract from either the package install or this source checkout."""
    path = root / "agents" / f"{role}.toml"
    if not path.is_file():
        path = root / "packages" / "codex" / "agents" / f"{role}.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"role instructions unavailable: {error}") from error
    found = re.search(r'(?ms)^developer_instructions = """\n(.*?)^"""$', text)
    if not found:
        raise ValueError(f"role instructions malformed: {path}")
    return found.group(1)


def build_argv(role: str, root: Path, cwd: str | None = None) -> list[str]:
    """The exact command line; refuses any role that is not a guarded profile entry."""
    if not ROLE.match(role) or role not in guarded_roles(root):
        raise ValueError(f"{role!r} is not a guarded role in capabilities/profiles.json")
    project_config = project_codex_dir(Path(cwd or os.getcwd()))
    if project_config:
        raise ValueError(f"{project_config} is project Codex config that --ignore-user-config does not skip")
    command = json.dumps(sys.executable)
    args = json.dumps([str(root / "scripts" / "capability_mcp.py"), "--role", role])
    # JSON string syntax is valid TOML basic-string syntax, so json.dumps quotes the inline table safely.
    argv = [
        "codex",
        "exec",
        "--ignore-user-config",
        "-s",
        "read-only",
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.multi_agent=false",
    ]
    argv += ["-c", f"developer_instructions={json.dumps(role_instructions(root, role))}"]
    argv += ["-c", f"mcp_servers.cap-{role}={{command = {command}, args = {args}}}"]
    if role == "source-auditor":
        for approval in SOURCE_AUDITOR_APPROVALS:
            argv += ["-c", approval]
    if cwd:
        argv += ["-C", cwd]
    return argv + ["-"]


def contained(argv: list[str], role: str) -> bool:
    """True only when argv carries every containment setting and exactly this role's one MCP server."""
    overrides = [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == "-c"]
    servers = [o for o in overrides if o.startswith("mcp_servers.") and ".tools." not in o]
    approvals = [o for o in overrides if ".approval_mode=" in o]
    instructions = [o for o in overrides if o.startswith("developer_instructions=")]
    sandbox = [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == "-s"]
    return (
        argv[:2] == ["codex", "exec"]
        and "--ignore-user-config" in argv
        and sandbox == ["read-only"]
        and "features.shell_tool=false" in overrides
        and "features.multi_agent=false" in overrides
        and len(instructions) == 1
        and len(servers) == 1
        and servers[0].startswith(f"mcp_servers.cap-{role}=")
        and approvals == (list(SOURCE_AUDITOR_APPROVALS) if role == "source-auditor" else [])
        and argv[-1] == "-"
    )


def scrubbed_env() -> dict[str, str]:
    """Allowlisted variables only: no tokens, no loop state, nothing the role's tools could forward."""
    return {key: os.environ[key] for key in ENV_ALLOW if key in os.environ}


def emit(outcome: str, code: str, role: str) -> None:
    """Append a fail-open trace row for the launch or refusal."""
    try:
        module = importlib.import_module("hooks.scripts.lib.trace_row")
        session = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CLAUDE_SESSION_ID") or "unattributed"
        module.append_row("codex_role_session", outcome, code, session, inputs={"role": role})
    except (ImportError, AttributeError, OSError):
        pass


def parse(argv: list[str]) -> dict[str, str] | None:
    """`--role R --prompt-file F [--cwd D]` as a dict, or None for any other shape."""
    pairs = dict(zip(argv[::2], argv[1::2]))
    if len(argv) % 2 or len(pairs) != len(argv) // 2 or not {"--role", "--prompt-file"} <= set(pairs) <= OPTIONS:
        return None
    return pairs


def main(argv: list[str]) -> int:
    """Launch the contained session; exit 2 on a refusal (nothing is spawned), else codex's own exit status."""
    args = parse(argv)
    if args is None:
        print("usage: codex_role_session.py --role <agent> --prompt-file <file> [--cwd <dir>]", file=sys.stderr)
        return 2
    role, prompt = args["--role"], Path(args["--prompt-file"])
    try:
        command = build_argv(role, ROOT, args.get("--cwd"))
    except ValueError as error:
        print(f"codex_role_session: {error}", file=sys.stderr)
        emit("refused", "codex_role_session_refused", role[:40])
        return 2
    if not prompt.is_file():
        print(f"codex_role_session: prompt file {prompt} not found", file=sys.stderr)
        emit("refused", "codex_role_session_no_prompt", role)
        return 2
    emit("ok", "codex_role_session_launched", role)
    with prompt.open("rb") as stream:
        return subprocess.run(command, stdin=stream, env=scrubbed_env(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
