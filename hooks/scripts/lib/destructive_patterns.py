"""Recognize the established destructive command families without executing input."""

from __future__ import annotations

import re
import subprocess
from contextlib import suppress
from pathlib import Path

try:
    from hooks.scripts.lib.hook_telemetry import note_child
except ImportError:  # telemetry must never be able to break the hook
    with suppress(Exception):  # record the loss once per process instead of silently disabling telemetry
        from hooks.scripts.hook_common import log

        log("hook_telemetry unavailable (ImportError); telemetry disabled for this process")

    def note_child(hook: str, returncode: int) -> None:
        """Telemetry unavailable: no-op."""


def normalize_ifs(command: str) -> str:
    """Normalize IFS expansions using the hook's bounded literal rules."""
    lines: list[str] = []
    for line in command.split("\n"):
        line = re.sub(r"\$\{IFS:?\+([^}]*)\}", r"\1", line)
        line = re.sub(r"\$\{IFS(\}|[^A-Za-z0-9_:+}][^}]*\}|:[^+}][^}]*\})", " ", line)
        lines.append(re.sub(r"\$IFS([^A-Za-z0-9_]|$)", r" \1", line))
    return "\n".join(lines)


def git_output(cwd: str, *arguments: str, hook: str = "destructive_patterns") -> str:
    """Read a Git property, returning empty on repository or command failures."""
    try:
        result = subprocess.run(["git", "-C", cwd, *arguments], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    note_child(hook, result.returncode)
    return result.stdout.strip() if result.returncode == 0 else ""


def secret_path(command: str) -> bool:
    """Recognize secret names, editor copies, and committing glob prefixes."""
    lowered = command.lower()
    if re.search(r"(^|[^a-z0-9_-])\.env([^a-z0-9_.-]|$)", lowered):
        return True
    debracketed = re.sub(r"\[([a-z0-9])\]", r"\1*", lowered)
    pattern = r"(^|[^a-z0-9_.-])\.e(n(v)?)?[\]\[*?]"
    if any(re.search(pattern, value) for value in (lowered, debracketed)):
        return True
    tokens = re.findall(r"(?:^|[^a-z0-9_-])(\.env\.([a-z0-9_.-]+))", lowered)
    return any(suffix.split(".")[0] not in {"example", "sample", "template", "dist"} for _, suffix in tokens)


def force_permitted(cwd: str) -> bool:
    """Read the exact force-with-lease opt-in from the target repository."""
    root = git_output(cwd, "rev-parse", "--show-toplevel") or cwd
    try:
        return "git-push-force-with-lease" in (Path(root) / ".claude/destructive_allowlist").read_text().splitlines()
    except OSError:
        return False


def permanent_pattern(command: str, cwd: str) -> tuple[str, str]:
    """Return the first blocked pattern and its stable identifier, or empty values."""
    for line in command.split("\n"):
        if re.search(r"\bgit\s+clean\b", line, re.I):
            args = re.sub(r".*\bgit\s+clean\b", "", line)
            exempt = r"(^|\s)(--dry-run|--interactive|-[a-zA-Z]*[ni][a-zA-Z]*)(\s|$)"
            force = r"(^|\s)(--force|-[a-zA-Z]*f[a-zA-Z]*)(\s|$)"
            if not re.search(exempt, args) and re.search(force, args):
                return "git clean (force)", "git-clean-force"
    families = [
        (r"\bfind\b[^;|&\n]*(\s-delete|\s--delete)", "find -delete", "find-delete"),
        (r"\btruncate\s+(-s|--size[=\s])", "truncate -s/--size", "truncate-size"),
        (r"\bshred\b", "shred", "secure-wipe-delete"),
    ]
    for pattern, text, identifier in families:
        if any(re.search(pattern, line, re.I) for line in command.split("\n")):
            return text, identifier
    if secret_path(command):
        return ".env access", "dotenv-access"
    flat = command.replace("\\\n", "").replace("\n", " ")
    options = r"(-[cC]\s+\S+|--[a-zA-Z][a-zA-Z-]*(=\S*)?|-[a-zA-Z]+)"
    push = rf"\bgit\b(\s+{options}){{0,20}}\s+push\b"
    naked = r"(--force([^-]|$)|(^|\s)-[a-zA-Z]*f[a-zA-Z]*(\s|$))"
    if re.search(rf"{push}.*({naked}|--force-with-lease\b)", flat, re.I):
        lease = re.search(rf"{push}\s+.*--force-with-lease\b", flat, re.I)
        if not (lease and not re.search(rf"{push}.*{naked}", flat, re.I) and force_permitted(cwd)):
            return "git push --force", "git-push-force"
    original = [
        (r"\brm\s+(-[rRfF]+|--recursive|--force)", "rm-rf"),
        (r"\bgit\s+reset\s+--hard", "git-reset-hard"),
        (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", "drop-table"),
        (r"\bTRUNCATE\s+TABLE\b", "truncate-table"),
        (r"\bdd\s+if=", "dd-if"),
        (r"\bmkfs\.", "mkfs-format"),
        (r"\bchmod\s+-R\s+777", "chmod-r-777"),
        (r"\bgit\s+commit\s+.*--no-verify", "git-commit-no-verify"),
    ]
    for line in command.split("\n"):
        matches = [
            (match.start(), match[0], identifier)
            for pattern, identifier in original
            if (match := re.search(pattern, line, re.I))
        ]
        if matches:
            _, text, identifier = min(matches)
            return text, identifier
    return "", ""


def source_write(command: str, cwd: str) -> str:
    """Return a source-edit denial, preserving target-repository branch resolution."""
    extension = r"\.(py|ts|tsx|js|jsx|go)([\s'\"]|$)"
    plugin = r"(^|[\s/'\"])(skills/[^/]+/SKILL\.md|commands/[^/]+\.md)([\s'\"]|$)"
    source = f"{extension}|{plugin}"
    target = ""
    if re.search(r"^\s*(cp|mv)\b", command, re.I):
        target = command.split()[-1]
    elif re.search(r"\bdd\b.*\bof=", command, re.I):
        match = re.search(r"of=([^ \n]+)", command)
        target = match[1] if match else ""
    if target and re.search(source, target, re.I) and target_branch(target, cwd) in {"main", "master"}:
        return (
            f"In-Bash source write (cp/mv/dd) on main branch blocked.\nFull command: {command}\n"
            "Writing source files via cp/mv/dd on main is blocked. Switch to a feature branch."
        )
    editing = False
    # perl switches are case-sensitive and -I/-M/-e/... take arguments, so only a bare `i` in the cluster counts.
    in_place = r"(?:sed\b[^;|&\n]*?\s(?:-[a-zA-Z0-9]*i|--in)|perl\b[^;|&\n]*?\s(?-i:-[^\sCDeEFIMmx-]*i))"
    if re.search(rf"\b{in_place}\S*[^;|&\n]*({source})", command, re.I):
        target, editing = command.split()[-1], True
    elif re.search(rf">+\s*['\"]?[^ '\"]*({source})", command, re.I):
        match = re.search(r">+\s*([^ \n]+)", command)
        target = re.sub(r"['\"]", "", match[1]) if match else ""
        editing = True
    elif re.search(rf"\btee\b.*({source})", command, re.I):
        target, editing = command.split()[-1], True
    branch = target_branch(target, cwd) if editing else ""
    if branch in {"main", "master"}:
        return (
            f"In-Bash source edit on {branch} branch blocked.\nFull command: {command}\n"
            "Editing source files via sed/perl/redirect/tee on main is blocked. "
            "Switch to a feature branch or use the Edit tool."
        )
    return ""


def target_branch(target: str, cwd: str) -> str:
    """Resolve the target branch before falling back to the working directory."""
    path = Path(target)
    path = path if path.is_absolute() else Path(cwd) / path
    return git_output(str(path.parent), "branch", "--show-current") or git_output(cwd, "branch", "--show-current")


def workflow_substitution(command: str) -> bool:
    """Reject live substitution in workflow arguments with the narrow prose exemption."""
    flat = command.replace("\n", " ")
    script = r"scripts/(push|merge|post_review|post_evals)\.(?:sh|py)"
    subst = r"`|\$\(|<\(|>\("
    mentions = list(re.finditer(script, flat))
    if not mentions or not re.search(subst, flat):
        return False
    first = mentions[0].start()
    if len(mentions) != 1 or flat[:first].count('"') % 2 == 0:
        return bool(re.search(subst, flat[first:]))
    segment = next((part for part in re.findall(r'"[^\"]*"', flat) if re.search(script, part)), "")
    if re.fullmatch(rf'"{script}"', segment):
        return bool(re.search(subst, flat[first:]))
    if re.search(subst, segment):
        return len(re.findall(subst, flat)) != len(re.findall(subst, segment))
    return True
