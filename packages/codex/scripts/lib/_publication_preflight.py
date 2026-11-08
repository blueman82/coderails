"""Read-only checks for trusted publication helpers before action authority."""

from __future__ import annotations

import os
import re
import shlex
from io import StringIO
from pathlib import Path

from scripts import push

from . import manifest_policy


def _script_index(argv: list[str]) -> int | None:
    if not argv or not re.fullmatch(r"python(?:3(?:\.\d+)*)?", argv[0]):
        return None
    index = 1
    while index < len(argv):
        option = argv[index]
        if option == "--":
            return index + 1 if index + 1 < len(argv) and argv[index + 1] != "-" else None
        if option == "-" or option.startswith(("-c", "-m")):
            return None
        if not option.startswith("-"):
            return index
        if option in {"-W", "-X", "--check-hash-based-pycs"}:
            index += 2
        elif option.startswith(("-W", "-X")) or re.fullmatch(r"-[bBdEiIOPqRsSuvx]+", option):
            index += 1
        else:
            return None
    return None


def _raw_script(source: str, argv: list[str], index: int) -> str:
    stream = StringIO(source)
    lexer = shlex.shlex(stream, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens: list[tuple[str, str]] = []
    while True:
        start = stream.tell()
        token = lexer.get_token()
        if token is None:
            break
        tokens.append((token, source[start : stream.tell()]))
    tail = tokens[-len(argv) :]
    if len(tail) != len(argv) or [token for token, _ in tail[1:]] != argv[1:]:
        return ""
    return tail[index][1]


def _active_root(raw: str, expression: str) -> bool:
    quote = ""
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in "'\"" and (not quote or quote == char):
            quote = "" if quote else char
        elif quote != "'" and raw.startswith(expression, index):
            return True
        index += 1
    return False


def _helper_path(source: str, argv: list[str], index: int, cwd: str, plugin: Path) -> Path | None:
    argument = argv[index]
    variable = "PLUGIN_ROOT" if (plugin / ".codex-plugin/plugin.json").is_file() else "CLAUDE_PLUGIN_ROOT"
    for expression in (f"${{{variable}}}", f"${variable}"):
        if argument.startswith(expression + "/"):
            root = os.environ.get(variable, "")
            if not Path(root).is_absolute() or not _active_root(_raw_script(source, argv, index), expression):
                return None
            return Path(root, argument[len(expression) + 1 :]).resolve()
    return (Path(cwd) / argument).resolve()


def push_preflight(calls: list[tuple[str, list[str], str]], session: str) -> str:
    """Validate this provider's direct Python push-helper calls before authority processing."""
    plugin = Path(__file__).resolve().parents[2]
    helper = plugin / "scripts/push.py"
    for source, argv, cwd in calls:
        index = _script_index(argv)
        if index is None:
            continue
        try:
            if _helper_path(source, argv, index, cwd, plugin) != helper:
                continue
            if not Path(cwd).is_absolute() or not manifest_policy.publication_session(session):
                raise ValueError("publication directory or session missing")
            _, _, _, unit, progress = push.parse_arguments(argv[index + 1 :])
            if (unit is None) != (progress is None):
                raise ValueError("--unit and --progress must be provided together")
            if unit is None or progress is None:
                if manifest_policy.active_graph_unit(cwd=cwd, session=session):
                    raise ValueError("graph unit requires --unit and --progress")
                continue
            manifest_policy.unit_manifest(progress, unit, cwd=cwd, session=session)
        except (OSError, ValueError, RuntimeError) as error:
            return f"diff_manifest:manifest_unreadable: Blocked: push publication check failed: {error}"
    return ""


def trace_preflight(code: str) -> None:
    """Count a repository or base retarget refusal before PR evidence can be trusted."""
    manifest_policy.trace("merge-preflight", "refused", code, command="publication")
