"""Quote-aware shell segments, supported wrappers and invocation-local directories."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from typing import cast

_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
_REDIRECT = re.compile(r"\d*(?:[<>]|&>)")
_BARE_REDIRECT = re.compile(r"\d*(?:>>?|<|>\||&>>?)")
_KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "do", "while", "until", "builtin"}
_WRAPPERS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "env": ("uCS", ("--unset", "--chdir", "--split-string"), 0),
    "sudo": ("ugphCDRT", ("--user", "--group", "--host", "--prompt", "--chdir", "--chroot", "--close-from"), 0),
    "command": ("", (), 0),
    "time": ("fo", ("--format", "--output"), 0),
    "nohup": ("", (), 0),
    "nice": ("n", ("--adjustment",), 0),
    "exec": ("a", (), 0),
    "timeout": ("sk", ("--signal", "--kill-after"), 1),
    "stdbuf": ("ioe", (), 0),
    "setsid": ("", (), 0),
    "xargs": ("InPsLdEa", (), 0),
    "uv": ("pw", ("--with", "--python", "--project", "--directory"), 1),
}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_FALLBACK_SPLIT = re.compile(r"&&|\|\||[;|&()\n]")


class OpaqueShellError(ValueError):
    """A command body would execute beyond the parser's bounded recursion."""


def move(cwd: str, target: str) -> str:
    """Compose a supported literal directory with its invocation directory."""
    return os.path.normpath(os.path.join(cwd, target)) if target else cwd


def raw_segments(command: str) -> list[str]:
    """Split outside quotes, retaining subshell boundaries and exact segment text."""
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
        elif char == "#" and (not current or current[-1] in " \t"):
            index = command.find("\n", index) - 1 if "\n" in command[index:] else len(command)
        elif char in ";&|()\n`" and not (
            char == "&" and (current[-1:] in (["<"], [">"]) or command[index + 1 : index + 2] == ">")
        ):
            segments.append("".join(current))
            current = []
            if char in "()":
                segments.append(char)
        else:
            current.append(char)
        index += 1
    if quote:
        raise ValueError("unterminated quote")
    return [*segments, "".join(current)]


def split_all(command: str) -> list[tuple[str, list[str]]]:
    """Keep source segments beside parsed argv; malformed input uses the existing conservative fallback."""
    try:
        return [(part.strip(), tokens) for part in raw_segments(command) if (tokens := shlex.split(part))]
    except ValueError:
        return [
            (part.strip(), tokens)
            for part in _FALLBACK_SPLIT.split(command)
            if (tokens := part.replace("'", " ").replace('"', " ").split())
        ]


def quoted_commands(source: str) -> list[str]:
    """Find command substitutions that remain executable inside double quotes."""
    found: list[str] = []
    quote = ""
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in "'\"" and (not quote or quote == char):
            quote = "" if quote else char
        elif quote == '"' and source.startswith("$(", index):
            start, depth, inner_quote = index + 2, 1, ""
            end = start
            while end < len(source) and depth:
                token = source[end]
                if token == "\\" and inner_quote != "'":
                    end += 2
                    continue
                if token in "'\"" and (not inner_quote or inner_quote == token):
                    inner_quote = "" if inner_quote else token
                elif not inner_quote:
                    if token == "(":
                        depth += 1
                    elif token == ")":
                        depth -= 1
                end += 1
            if depth == 0:
                found.append(source[start : end - 1])
                index = end
                continue
        elif quote == '"' and char == "`":
            end = index + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                elif source[end] == "`":
                    found.append(source[index + 1 : end])
                    index = end + 1
                    break
                else:
                    end += 1
            else:
                index = end
            continue
        index += 1
    return found


def strip_wrapper(name: str, argv: list[str], cwd: str) -> tuple[list[str], str]:
    """Drop a supported wrapper's options and retain its local directory selection."""
    short, long_options, positionals = _WRAPPERS[name]
    directories = {"env": {"-C", "--chdir"}, "sudo": {"-D", "--chdir"}, "uv": {"--directory"}}
    while argv:
        token = argv[0]
        option, separator, attached = token.partition("=")
        if name == "env" and option in ("-S", "--split-string") and (separator or len(argv) > 1):
            value = attached if separator else argv[1]
            try:
                values = shlex.split(value)
            except ValueError:
                values = value.split()
            return [*values, *argv[1 if separator else 2 :]], cwd
        if option in directories.get(name, set()):
            if not separator and len(argv) < 2:
                return [], cwd
            cwd = move(cwd, attached if separator else argv[1])
        if token.startswith("--") and token != "--":
            skip = 2 if token in long_options else 1
        elif token.startswith("-") and len(token) > 1:
            skip = 2 if len(token) == 2 and token[1] in short else 1
            if token[:2] in directories.get(name, set()) and len(token) > 2:
                cwd = move(cwd, token[2:])
        elif _ASSIGN.match(token):
            skip = 1
        elif positionals:
            positionals -= 1
            skip = 1
        else:
            break
        argv = argv[skip:]
    return argv, cwd


def unwrap(argv: list[str], cwd: str) -> tuple[list[str], str]:
    """Remove supported wrappers without changing the caller's outer directory."""
    while argv:
        head = argv[0]
        if _ASSIGN.match(head) or head in _KEYWORDS:
            argv = argv[1:]
        elif _REDIRECT.match(head):
            argv = argv[2 if _BARE_REDIRECT.fullmatch(head) else 1 :]
        elif os.path.basename(head) in _WRAPPERS:
            argv, cwd = strip_wrapper(os.path.basename(head), argv[1:], cwd)
        else:
            return [os.path.basename(head), *argv[1:]], cwd
    return [], cwd


def shell_body(argv: list[str]) -> str | None:
    """Read the literal command body after supported shell options."""
    if not argv or argv[0] not in SHELLS:
        return None
    position = 1
    while position < len(argv) and argv[position].startswith(("-", "+")):
        token = argv[position]
        if token in ("-o", "+o", "-O", "+O"):
            position += 1
        elif not token.startswith("--") and "c" in token and position + 1 < len(argv):
            return argv[position + 1]
        position += 1
    return None


def ansi_c_quote(source: str) -> bool:
    """Detect active Bash $'...' quoting without matching inert single-quoted text."""
    quote = ""
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char == "$" and source[index + 1 : index + 2] == "'":
            return True
        elif char in "'\"":
            quote = char
        index += 1
    return False


def shell_c_requested(argv: list[str]) -> bool:
    """Recognize a -c option whose body the bounded parser could not locate."""
    return any(token.startswith("-") and not token.startswith("--") and "c" in token[1:] for token in argv[1:])


def invocations(
    command: str, cwd: str = "", depth: int = 0, *, strict: bool = False
) -> list[tuple[str, list[str], str]]:
    """Yield exact source, unwrapped argv and effective cwd, with local shell/subshell scope."""
    found: list[tuple[str, list[str], str]] = []
    directories: list[str] = []
    cursor = 0
    for segment, tokens in split_all(command):
        if strict and ansi_c_quote(segment):
            raise OpaqueShellError("ANSI-C quoted shell syntax is opaque")
        at = command.find(segment, cursor)
        if at < 0:
            at = cursor
        cursor = at + len(segment)
        if segment == "(":
            directories.append(cwd)
            continue
        if segment == ")":
            if directories:
                cwd = directories.pop()
            continue
        argv, where = unwrap(tokens, cwd)
        for embedded in quoted_commands(segment):
            if depth >= 5:
                if strict:
                    raise OpaqueShellError("quoted command exceeds shell depth")
            else:
                found.extend(invocations(embedded, cwd, depth + 1, strict=strict))
        if not argv:
            continue
        if argv[0] == "cd":
            args = argv[2:] if len(argv) > 1 and argv[1] == "--" else argv[1:]
            before = command[:at].rstrip()
            after = command[cursor:].lstrip()
            child_shell = (before.endswith(("|", "&")) and not before.endswith(("||", "&&"))) or (
                after.startswith(("|", "&")) and not after.startswith(("||", "&&"))
            )
            if len(args) == 1 and not child_shell:
                cwd = move(where, args[0])
            continue
        found.append((segment, argv, where))
        body = shell_body(argv)
        if strict and body is None and argv[0] in SHELLS and shell_c_requested(argv):
            raise OpaqueShellError("shell -c body follows unsupported options")
        if body is None and argv[0] == "eval" and len(argv) > 1:
            body = " ".join(argv[1:])
        if body is not None:
            if depth >= 5:
                if strict:
                    raise OpaqueShellError("shell command exceeds shell depth")
            else:
                found.extend(invocations(body, where, depth + 1, strict=strict))
    return found


def opaque_execution(command: str, cwd: str = "") -> bool:
    """True if supported shell forms would execute beyond the parser's depth limit."""
    try:
        invocations(command, cwd, strict=True)
    except OpaqueShellError:
        return True
    return False


def payload_cwd(payload: Mapping[str, object]) -> str:
    """Read the native tool workdir before payload cwd and process cwd."""
    data = payload.get("tool_input")
    workdir = cast(dict[str, object], data).get("workdir") if isinstance(data, dict) else None
    cwd = workdir if isinstance(workdir, str) and workdir else payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()
