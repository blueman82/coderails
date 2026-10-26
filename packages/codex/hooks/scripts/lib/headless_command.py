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
    "--agent",
    "--fallback-model",
    "--effort",
    "--add-dir",
    "--output-schema",
    "--thread-source",
    "--enable",
    "--disable",
    "--output-last-message",
    "--local-provider",
    "--ask-for-approval",
    "-a",
    "--color",
    "--cyber-access-program",
    "--permission-prompts",
    "--plugin-dir",
    "--plugin-url",
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
    if program not in {"claude", "codex"}:
        return ""
    options = args[1:]
    if program == "claude" and not any(arg in {"-p", "--print"} for arg in options):
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
    if program == "codex":
        if not prompts or prompts[0] not in {"exec", "e"}:
            return ""
        prompts.pop(0)
    return prompts[0] if len(prompts) == 1 else ""


def headless_cwd_override(segment: str) -> bool:
    """A child with its own working directory cannot use the parent's PR evidence."""
    try:
        args = shlex.split(segment)
    except ValueError:
        return False
    return any(arg.startswith("-C") or arg == "--cd" or arg.startswith("--cd=") for arg in args[1:])
