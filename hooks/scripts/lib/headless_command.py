"""Find command prompts in headless agent calls without reading inert quoted text."""

from __future__ import annotations

import os
import shlex

_HEADLESS_VALUE_OPTIONS = {
    "--permission-mode",
    "--system-prompt",
    "--append-system-prompt",
    "--model",
    "--output-format",
    "--allowedTools",
    "--disallowedTools",
    "--mcp-config",
    "--settings",
    "--session-id",
    "--resume",
    "--agents",
    "--tools",
    "--betas",
    "--json-schema",
    "--cd",
    "-C",
    "-m",
    "--sandbox",
    "-s",
    "--output",
    "-o",
    "--config",
    "-c",
    "--profile",
    "--image",
    "-i",
}


def headless_prompt(segment: str) -> str:
    """Return one command prompt passed to a headless Claude or Codex child."""
    try:
        args = shlex.split(segment)
    except ValueError:
        return ""
    if not args:
        return ""
    program = os.path.basename(args[0])
    if program == "claude":
        mode = any(arg in {"-p", "--print"} for arg in args[1:])
        options = args[1:]
    elif program == "codex" and len(args) > 1 and args[1] == "exec":
        mode, options = True, args[2:]
    else:
        return ""
    if not mode:
        return ""
    prompts: list[str] = []
    skip = False
    for arg in options:
        if skip:
            skip = False
        elif arg in _HEADLESS_VALUE_OPTIONS:
            skip = True
        elif arg.startswith("-"):
            continue
        else:
            prompts.append(arg)
    return prompts[0] if len(prompts) == 1 else ""
