"""Git and script policy classifiers over the shared shell-context producer."""

from __future__ import annotations

import os
import re

from .shell_context import SHELLS, invocations, move

_GIT_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
_LONG_ARG = {"--message", "--file", "--author", "--date", "--template", "--reuse-message", "--reedit-message"}


def argvs(command: str) -> list[list[str]]:
    """Every supported invocation, with wrappers removed and command basenames."""
    return [argv for _, argv, _ in invocations(command)]


def git_invocation(argv: list[str], cwd: str = "") -> tuple[str, str, list[str]] | None:
    """Return subcommand, composed invocation directory and remaining Git arguments."""
    if not argv or argv[0] != "git":
        return None
    index, directory = 1, cwd
    while index < len(argv) and argv[index].startswith("-"):
        token = argv[index]
        if token in _GIT_ARG:
            if index + 1 >= len(argv):
                return None
            if token == "-C":
                directory = move(directory, argv[index + 1])
            index += 2
        else:
            if token.startswith("-C") and len(token) > 2:
                directory = move(directory, token[2:])
            index += 1
    return (argv[index], directory, argv[index + 1 :]) if index < len(argv) else None


def git_calls(command: str, cwd: str = "") -> list[tuple[str, str, list[str]]]:
    """Every Git invocation, preserving its local shell and successive -C directory."""
    return [call for _, argv, where in invocations(command, cwd) if (call := git_invocation(argv, where))]


def git_prefix(argv: list[str], rest: list[str]) -> list[str]:
    """Return the original global prefix from an already classified Git invocation."""
    return argv[1 : len(argv) - len(rest) - 1]


def flags(rest: list[str], takes: str = "") -> set[str]:
    """Decode long options and short clusters, excluding values of known options."""
    found: set[str] = set()
    skip = False
    for token in rest:
        if skip:
            skip = False
        elif token == "--":
            break
        elif token.startswith("--"):
            found.add(token.split("=")[0])
            skip = token in _LONG_ARG
        elif token.startswith("-") and len(token) > 1:
            for position, char in enumerate(token[1:], 1):
                found.add(f"-{char}")
                if char in takes:
                    skip = position == len(token) - 1
                    break
    return found


def is_script(argv: list[str], names: str | tuple[str, ...], ops: str | tuple[str, ...] = ()) -> bool:
    """Recognize a real script operation rather than a filename or operation mentioned as an argument."""
    wanted = {names} if isinstance(names, str) else set(names)
    allowed = {ops} if isinstance(ops, str) else set(ops)
    rest = argv[1:]
    script = argv[0] if argv else ""
    python = bool(re.fullmatch(r"python[\d.]*", script))
    if python or script in SHELLS:
        valued = ("-W", "-X") if python else ("-o", "-O")
        script = ""
        while rest:
            token, rest = rest[0], rest[1:]
            if token == "-c":
                return False
            if token == "-m" and python and rest:
                script, rest = rest[0].replace(".", "/") + ".py", rest[1:]
            elif token in valued:
                rest = rest[1:]
            elif not token.startswith("-"):
                script = token
            if script:
                break
    if os.path.basename(script) not in wanted:
        return False
    if not allowed:
        return True
    while rest and rest[0].startswith("-"):
        if rest[0] == "--":
            rest = rest[1:]
            break
        option = rest[0].split("=")[0]
        if not option.startswith("--") or not "--progress".startswith(option):
            return False
        rest = rest[1 if "=" in rest[0] else 2 :]
    return bool(rest) and rest[0] in allowed
