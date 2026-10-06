"""Argv-level command classifier shared by the Claude and Codex gates (byte-identical copies).

Splits a Bash command into argv lists on ; && || | & ( ) backtick and newline outside quotes (a `#` comment is
dropped), unwraps assignments, leading redirections, shell keywords ({ } ! if then do ...), per-wrapper options
(env sudo command exec time nohup nice timeout stdbuf setsid xargs builtin uv run), absolute paths and
`bash [-o x] -c '...'`, and recognises git subcommands and scripts by argv, so quoted text (`echo "git commit"`)
is one token and never matches.
Limits (no shell parser): eval, aliases (`git -c alias.ci=commit ci`), functions, `$'git'` quoting, backticks
inside double quotes and scripts that themselves commit are not seen. A shlex failure (unbalanced quote) falls
back to a whitespace split of the raw segments: plain words over-match, but a `-c` body split by that fallback
is seen only as its first word.
"""

from __future__ import annotations

import os
import re
import shlex

_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
_REDIRECT = re.compile(r"\d*(?:[<>]|&>)")
_BARE_REDIRECT = re.compile(r"\d*(?:>>?|<|>\||&>>?)")
_KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "do", "while", "until", "builtin"}
# wrapper -> (short options taking a value, long options taking a value, leading positionals to skip)
_WRAPPERS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "env": ("uCS", ("--unset", "--chdir", "--split-string"), 0),
    "sudo": ("ugphCDRT", ("--user", "--group", "--host", "--prompt", "--chdir", "--chroot", "--close-from"), 0),
    "command": ("", (), 0),
    "time": ("", (), 0),
    "nohup": ("", (), 0),
    "nice": ("n", ("--adjustment",), 0),
    "exec": ("a", (), 0),
    "timeout": ("sk", ("--signal", "--kill-after"), 1),
    "stdbuf": ("ioe", (), 0),
    "setsid": ("", (), 0),
    "xargs": ("InPsLdEa", (), 0),
    "uv": ("pw", ("--with", "--python", "--project", "--directory"), 1),
}
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
        elif char == "#" and (not current or current[-1] in " \t"):  # comment: drop to end of line
            index = command.find("\n", index) - 1 if "\n" in command[index:] else len(command)
        elif char in ";&|()\n`" and not (
            char == "&" and (current[-1:] in (["<"], [">"]) or command[index + 1 : index + 2] == ">")
        ):
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
        head = argv[0]
        if _ASSIGN.match(head) or head in _KEYWORDS:
            argv = argv[1:]
        elif _REDIRECT.match(head):
            argv = argv[2 if _BARE_REDIRECT.fullmatch(head) else 1 :]
        elif os.path.basename(head) in _WRAPPERS:
            argv = _strip_wrapper(os.path.basename(head), argv[1:])
        else:
            break
    if not argv:
        return
    argv = [os.path.basename(argv[0]), *argv[1:]]
    found.append(argv)
    if argv[0] in _SHELLS and depth < 5:
        position = 1
        while position < len(argv) and argv[position].startswith(("-", "+")):
            token = argv[position]
            if token in ("-o", "+o", "-O", "+O"):  # option with a value
                position += 1
            elif not token.startswith("--") and "c" in token and position + 1 < len(argv):
                for inner in _split_all(argv[position + 1]):
                    _unwrap(inner, found, depth + 1)
                break
            position += 1


def _strip_wrapper(name: str, argv: list[str]) -> list[str]:
    """Drop a wrapper's options (and the values of those that take one), assignments and leading positionals."""
    short, long_options, positionals = _WRAPPERS[name]
    while argv:
        token = argv[0]
        if name == "env" and token in ("-S", "--split-string") and len(argv) > 1:
            try:
                return [*shlex.split(argv[1]), *argv[2:]]
            except ValueError:
                return [*argv[1].split(), *argv[2:]]
        if token.startswith("--") and token != "--":
            skip = 2 if token in long_options else 1
        elif token.startswith("-") and len(token) > 1:
            skip = 2 if len(token) == 2 and token[1] in short else 1
        elif _ASSIGN.match(token):
            skip = 1
        elif positionals:
            positionals -= 1
            skip = 1
        else:
            break
        argv = argv[skip:]
    return argv


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
    python = bool(re.fullmatch(r"python[\d.]*", script))
    if python or script in _SHELLS:
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
