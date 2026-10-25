#!/usr/bin/env python3
"""Detect missing memory injection caps and repair only explicit opt-in installs."""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, cast

CAP_EVIDENCE = 'head -c "$REMEMBER_INJECT_MAX_BYTES"'
SENTINEL = "REMEMBER_INJECT_MAX_BYTES"


def notify(message: str) -> None:
    """Expose a SessionStart advisory to both the human and the model."""
    print(
        json.dumps(
            {
                "systemMessage": message,
                "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message},
            }
        )
    )


def version_key(version: str) -> list[tuple[int, str]]:
    """Sort conventional plugin version segments numerically."""
    return [(int(piece), "") if piece.isdigit() else (-1, piece) for piece in re.split(r"(\d+)", version)]


def resolve_install(plugins: Path) -> tuple[str, Path]:
    """Prefer an existing user install before newest scoped or cached installs."""
    try:
        raw: object = json.loads((plugins / "installed_plugins.json").read_text())
        manifest = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        manifest = {}
    entries: list[tuple[str, str, Path]] = []
    installed = manifest.get("plugins")
    if isinstance(installed, dict):
        for name, records in cast(dict[str, Any], installed).items():
            if not str(name).startswith("remember@") or not isinstance(records, list):
                continue
            for record in cast(list[object], records):
                if not isinstance(record, dict) or not isinstance(cast(dict[str, Any], record).get("installPath"), str):
                    continue
                path = Path(cast(dict[str, Any], record)["installPath"])
                if path.is_dir():
                    entries.append(
                        (
                            str(cast(dict[str, Any], record).get("scope", "unknown")),
                            str(cast(dict[str, Any], record).get("version", "unknown")),
                            path,
                        )
                    )
    if entries:
        chosen = next((entry for entry in entries if entry[0] == "user"), None)
        chosen = chosen or max(entries, key=lambda entry: version_key(entry[1]))
        return chosen[1], chosen[2]
    candidates = sorted(path for path in plugins.glob("cache/*/remember/*") if path.is_dir())
    if candidates:
        latest = max(candidates, key=lambda path: version_key(path.name))
        return latest.name, latest
    return "", Path()


def apply_cap(target: Path, version: str, patch_directory: Path, source: str) -> None:
    """Replace exactly one canonical block after backup and verify before replacement."""
    prefix = f"coderails: the memory-injection byte cap is MISSING from the remember plugin (version {version})"
    try:
        vendor = (patch_directory / "remember_inject_cap.vendor.txt").read_text().splitlines()
        replacement = (patch_directory / "remember_inject_cap.patched.txt").read_text().splitlines()
    except OSError:
        notify(
            f"{prefix}, and the canonical patch text was not found under {patch_directory}. Re-apply the cap by hand."
        )
        return
    lines = source.splitlines()
    matches = [index for index in range(len(lines) - len(vendor) + 1) if lines[index : index + len(vendor)] == vendor]
    if len(matches) != 1:
        notify(
            f"{prefix}, but its session-start-hook.sh no longer has the shape the patch expects "
            f"(found {len(matches)} matching blocks, expected exactly 1). Nothing was "
            f"changed — re-apply the cap by hand at {target}."
        )
        return
    backup = Path(f"{target}.coderails-bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    try:
        shutil.copy2(target, backup)
    except OSError:
        with suppress(OSError):
            backup.unlink()
        notify(
            f"{prefix}, but a backup of {target} could not be written, so nothing was "
            f"changed. Re-apply the cap by hand."
        )
        return
    for old in target.parent.glob(target.name + ".coderails-bak-*"):
        if old != backup and old.is_file():
            with suppress(OSError):
                old.unlink()
    temporary = Path(f"{target}.coderails-tmp.{os.getpid()}")
    index = matches[0]
    proposed = "\n".join(lines[:index] + replacement + lines[index + len(vendor) :]) + "\n"
    try:
        temporary.write_text(proposed)
        if not proposed.strip() or CAP_EVIDENCE not in proposed:
            notify(
                f"coderails: the re-applied memory-injection byte cap did not verify, so {target} was left unchanged "
                f"(backup at {backup}). Re-apply by hand."
            )
            return
        with suppress(OSError):
            temporary.chmod(target.stat().st_mode)
        os.replace(temporary, target)
    except OSError:
        notify(
            f"coderails: could not replace {target} with the re-patched version (backup at {backup}). "
            "Re-apply the memory-injection byte cap by hand."
        )
        return
    finally:
        with suppress(OSError):
            temporary.unlink()
    cap = os.environ.get("REMEMBER_INJECT_MAX_BYTES", "8000")
    notify(
        f"coderails: re-applied the memory-injection byte cap to the remember plugin (version {version}). "
        "The plugin was updated, which installed a fresh unpatched copy of session-start-hook.sh and wiped the "
        f"hand-applied cap. Memory files are capped at {cap} bytes each again (override with {SENTINEL}). "
        f"Original saved to {backup}."
    )


def main() -> int:
    """Warn once per plugin version, or perform the previously authorized literal patch."""
    explicit = os.environ.get("REMEMBER_HOOK_FILE", "")
    version = os.environ.get("REMEMBER_PLUGIN_VERSION", "unknown")
    if explicit:
        target = Path(explicit)
    else:
        version, install = resolve_install(
            Path(os.environ.get("CLAUDE_PLUGINS_DIR", str(Path.home() / ".claude/plugins")))
        )
        if not version:
            return 0
        target = install / "scripts/session-start-hook.sh"
    try:
        source = target.read_text()
    except OSError:
        notify(
            f"coderails: cannot read the remember plugin's session-start-hook.sh at {target} — the memory-injection "
            "byte cap could not be checked. Re-apply it by hand if the plugin layout changed."
        )
        return 0
    if CAP_EVIDENCE in source:
        return 0
    if os.environ.get("REMEMBER_INJECT_CAP_AUTOWRITE", "0") != "1":
        state = Path(os.environ.get("REMEMBER_INJECT_STATE_DIR", str(Path.home() / ".claude/coderails")))
        stamp = state / "remember_inject_cap_warned"
        with suppress(OSError):
            if stamp.read_text().strip() == version:
                return 0
        notify(
            f"coderails: the remember plugin (version {version}) does not have the memory-injection byte cap applied. "
            f"That cap truncates each memory file the plugin injects at session start to "
            f"{SENTINEL} bytes (default 8000), "
            "which cuts token burn on large memory files. coderails will NOT modify another plugin's files without "
            "your permission, so nothing has been changed. To let coderails apply and re-apply it automatically, add "
            '"REMEMBER_INJECT_CAP_AUTOWRITE": "1" to the "env" block of your settings.json '
            "(~/.claude/settings.json for all projects, or .claude/settings.json in one "
            "project). Otherwise ignore this "
            "— it will not be repeated until the plugin version changes."
        )
        with suppress(OSError):
            state.mkdir(parents=True, exist_ok=True)
            stamp.write_text(version + "\n")
        return 0
    patches = Path(os.environ.get("REMEMBER_PATCH_DIR", str(Path(__file__).resolve().parents[1] / "patches")))
    apply_cap(target, version, patches, source)
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("remember_inject_cap_guard", main))
