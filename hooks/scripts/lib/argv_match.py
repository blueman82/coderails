"""Argv-level command classifier shared by the Claude and Codex gates (byte-identical copies).

Splits a Bash command into argv lists on ; && || | & ( ) and newline outside quotes, unwraps
env/sudo/command/exec/time/nohup/nice, absolute paths and `bash -c '...'`, and recognises git subcommands and
scripts by argv, so quoted text (`echo "git commit"`) is one token and never matches.
Limits (no shell parser): eval, xargs, aliases, functions and scripts that themselves commit are not seen.
A shlex failure (unbalanced quote) falls back to a whitespace split of the raw segments, which over-matches.
"""

from __future__ import annotations

import os
import re
import shlex

_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
_WRAPPERS = {"env", "sudo", "command", "exec", "time", "nohup", "nice"}
_WRAPPER_ARG = {"-u", "-g", "-h", "-p", "-C", "-D", "-n", "-o", "-a"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_GIT_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
_LONG_ARG = {"--message", "--file", "--author", "--date", "--template", "--reuse-message", "--reedit-message"}
_FALLBACK_SPLIT = re.compile(r"&&|\|\||[;|&()\n]")


def _raw_segments(command: str) -> list[str]:
    """Split on separators outside quotes; raise ValueError on an unterminated quote."""
    command = command.replace("\\\n", " ")
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            current.append(command[index : index + 2])
            index += 1
        elif quote:
            current.append(char)
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in ";&|()\n":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if quote:
        raise ValueError("unterminated quote")
    return [*segments, "".join(current)]


def _split_all(command: str) -> list[list[str]]:
    """Return argv lists per segment, falling back conservatively when shlex cannot parse."""
    try:
        return [tokens for part in _raw_segments(command) if (tokens := shlex.split(part))]
    except ValueError:
        parts = (part.replace("'", " ").replace('"', " ").split() for part in _FALLBACK_SPLIT.split(command))
        return [tokens for tokens in parts if tokens]


def _unwrap(argv: list[str], found: list[list[str]], depth: int) -> None:
    """Strip wrappers and assignments, record the command with a basename argv[0], and recurse into shell -c."""
    while argv:
        if _ASSIGN.match(argv[0]):
            argv = argv[1:]
        elif os.path.basename(argv[0]) in _WRAPPERS:
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or _ASSIGN.match(argv[0])):
                skip = 2 if argv[0] in _WRAPPER_ARG and len(argv) > 1 else 1
                argv = argv[skip:]
        else:
            break
    if not argv:
        return
    argv = [os.path.basename(argv[0]), *argv[1:]]
    found.append(argv)
    if argv[0] in _SHELLS and depth < 5:
        for position, token in enumerate(argv[1:], 1):
            if not token.startswith("-"):
                break
            if not token.startswith("--") and "c" in token and position + 1 < len(argv):
                for inner in _split_all(argv[position + 1]):
                    _unwrap(inner, found, depth + 1)
                break


def argvs(command: str) -> list[list[str]]:
    """Every invocation in the command (wrappers removed, argv[0] reduced to its basename)."""
    found: list[list[str]] = []
    for argv in _split_all(command):
        _unwrap(argv, found, 0)
    return found


def git_invocation(argv: list[str]) -> tuple[str, str, list[str]] | None:
    """Return (subcommand, -C dir, remaining args) for a git argv, skipping git's global options."""
    if not argv or argv[0] != "git":
        return None
    index, directory = 1, ""
    while index < len(argv) and argv[index].startswith("-"):
        if argv[index] == "-C" and index + 1 < len(argv):
            directory = argv[index + 1]
        index += 2 if argv[index] in _GIT_ARG else 1
    return (argv[index], directory, argv[index + 1 :]) if index < len(argv) else None


def git_calls(command: str) -> list[tuple[str, str, list[str]]]:
    """Every git invocation in the command as (subcommand, -C dir, remaining args)."""
    return [call for argv in argvs(command) if (call := git_invocation(argv))]


def flags(rest: list[str], takes: str = "") -> set[str]:
    """Decode options: long names without =value, short clusters split (`-nm` -> -n, -m).

    `takes` lists short options whose value is the rest of the cluster or the next token, so `-m -n` is not -n.
    """
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
    """Whether argv runs a script with one of these basenames (directly or via an interpreter) and operation."""
    wanted = {names} if isinstance(names, str) else set(names)
    allowed = {ops} if isinstance(ops, str) else set(ops)
    rest = argv[1:]
    script = argv[0] if argv else ""
    if re.fullmatch(r"python[\d.]*", script) or script in _SHELLS:
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        script, rest = (rest[0], rest[1:]) if rest else ("", [])
    return os.path.basename(script) in wanted and (not allowed or bool(rest) and rest[0] in allowed)
