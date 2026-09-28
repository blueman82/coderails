"""Manage Claude marketplace registration, discipline text and memory seeds."""

import contextlib
import json
import shutil
import time
from pathlib import Path

from scripts.lib.artifact_io import JsonObject, object_value, read_object

from .files import atomic_bytes, confirm

STALE = ("workflow-tools", "claude-guardrails")
COMMANDS = (
    "workflow",
    "init",
    "prep",
    "push",
    "merge",
    "assumptions",
    "notchecked",
    "disconfirm",
    "verify",
    "test-gate-setup",
)
HEADING = "## Self-Checking Discipline"


def preflight(home: Path) -> None:
    """Refuse old installed plugins that would otherwise fire duplicate hooks."""
    installed = home / ".claude/plugins/installed_plugins.json"
    if not installed.is_file():
        return
    plugins = object_value(read_object(installed).get("plugins", {}))
    stale = [key for key in plugins if any(key.startswith(f"{name}@") for name in STALE)]
    if stale:
        commands = "\n".join(f"/plugin uninstall {key.rsplit('@', 1)[0]}" for key in stale)
        raise ValueError(
            f"SUPERSEDED PLUGINS STILL INSTALLED\n{commands}\nMIGRATION REQUIRED — uninstall above, then re-run"
        )


def save_json(path: Path, data: JsonObject) -> None:
    """Back up an existing registry before replacing it with valid UTF-8 JSON."""
    if path.exists():
        shutil.copy2(path, f"{path}.bak")
    atomic_bytes(path, (json.dumps(data, indent=2) + "\n").encode())


def prune_empty_cache(directory: Path) -> None:
    """Remove only empty stale directories, never files or symlink targets."""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        if not (any(name in entry.name for name in STALE) or entry.name.startswith('"$HOME')):
            continue
        paths = sorted(entry.rglob("*"), key=lambda path: len(path.parts), reverse=True)
        for path in [*paths, entry]:
            if path.is_dir() and not path.is_symlink():
                with contextlib.suppress(OSError):
                    path.rmdir()


def register(root: Path, home: Path) -> None:
    """Register this directory marketplace while stripping only superseded keys."""
    settings = home / ".claude/settings.json"
    data = read_object(settings) if settings.exists() else {}
    marketplaces = object_value(data.get("extraKnownMarketplaces", {}))
    marketplaces["coderails"] = {"source": {"source": "directory", "path": str(root)}}
    for name in STALE:
        marketplaces.pop(name, None)
    data["extraKnownMarketplaces"] = marketplaces
    save_json(settings, data)
    known = home / ".claude/plugins/known_marketplaces.json"
    if known.exists():
        registry = read_object(known)
        for name in STALE:
            registry.pop(name, None)
        save_json(known, registry)
    prune_empty_cache(home / ".claude/plugins/marketplaces")


def conflicts(root: Path, home: Path, *, dry_run: bool) -> None:
    """Offer only existing bare-command overwrites and default EOF to skip."""
    directory = home / ".claude/commands"
    targets = [directory / f"{name}.md" for name in COMMANDS if (directory / f"{name}.md").is_file()]
    if not targets:
        return
    print("EXISTING COMMAND FILES DETECTED")
    for target in targets:
        print(target)
    if dry_run:
        for target in targets:
            print(f"would: cp {root / 'commands' / target.name} → {target}")
    elif confirm("Overwrite? [y/N] "):
        for target in targets:
            shutil.copyfile(root / "commands" / target.name, target)
    else:
        print("skipped — existing commands unchanged")


def discipline_and_memory(root: Path, home: Path, memory: Path, *, dry_run: bool) -> None:
    """Append discipline once and seed only absent user feedback memories."""
    document = home / ".claude/CLAUDE.md"
    seeds = sorted((root / "starter-memory").glob("feedback_*.md"))
    if dry_run:
        print(f"would: append '{HEADING}' section → {document}")
        print(f"would: mkdir -p {memory}")
        for seed in seeds:
            print(f"would: cp {seed.name} → {memory}/ (skip if exists)")
        return
    original = document.read_text() if document.exists() else ""
    if HEADING not in original:
        lines = (root / "instructions/self-checking-discipline.md").read_text().splitlines(keepends=True)
        index = next((index for index, line in enumerate(lines) if line.startswith(HEADING)), len(lines))
        atomic_bytes(document, (original + "\n" + "".join(lines[index:])).encode())
    memory.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        target = memory / seed.name
        if not target.exists():
            shutil.copyfile(seed, target)


def install(root: Path, home: Path, memory: Path, *, dry_run: bool) -> None:
    """Apply the Claude-local installation after the migration preflight."""
    preflight(home)
    conflicts(root, home, dry_run=dry_run)
    if dry_run:
        print(f"would: merge extraKnownMarketplaces.coderails → {home / '.claude/settings.json'}")
        print(f"would: source.path = {root}")
        print("would: drop stale keys (settings + known_marketplaces): workflow-tools, claude-guardrails")
        print("would: remove empty stale marketplace cache dirs (if any)")
    else:
        register(root, home)
    discipline_and_memory(root, home, memory, dry_run=dry_run)
    print("Run in Claude Code: /plugin install coderails@coderails")


def uninstall(home: Path) -> None:
    """Remove only discipline and marketplace state, retaining personal data."""
    document = home / ".claude/CLAUDE.md"
    print("=== Remove discipline rules from CLAUDE.md ===")
    if document.is_file() and HEADING in document.read_text():
        shutil.copy2(document, f"{document}.bak.{int(time.time())}")
        output: list[str] = []
        removing = False
        for line in document.read_text().splitlines(keepends=True):
            if line.startswith(HEADING):
                removing = True
                continue
            if line.startswith("## "):
                removing = False
            if not removing:
                output.append(line)
        atomic_bytes(document, "".join(output).encode())
    for relative in ("settings.json", "plugins/known_marketplaces.json"):
        path = home / ".claude" / relative
        if not path.is_file():
            continue
        data = read_object(path)
        if relative == "settings.json":
            registry = object_value(data.get("extraKnownMarketplaces", {}))
            registry.pop("coderails", None)
            if "extraKnownMarketplaces" in data:
                data["extraKnownMarketplaces"] = registry
        else:
            data.pop("coderails", None)
        save_json(path, data)
    print("PRESERVED: ~/.claude/discipline.log and feedback memory files.")
    print("Then run: /plugin uninstall coderails (removes the hooks/commands/skills)")
