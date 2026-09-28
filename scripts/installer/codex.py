"""Install provider-native Codex agents after validating all collision boundaries."""

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .files import atomic_bytes

NAMES = (
    "deploy-safety-reviewer",
    "design-scout",
    "disposition-scout",
    "docs-auditor",
    "loop-worker",
    "preflight-scout",
    "proof-author",
    "source-auditor",
    "spec-reviewer",
    "wiki-writer",
)
MARKER = "# Managed by Coderails Codex plugin"


def preflight(root: Path, home: Path, timestamp: str) -> list[tuple[Path, Path]]:
    """Refuse any invalid agent or target before modifying the installation."""
    source_dir = root / "packages/codex/agents"
    target_dir = home / "agents"
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError(f"Invalid Codex agent source directory: {source_dir}")
    count = len([path for path in source_dir.glob("*.toml") if path.is_file() and not path.is_symlink()])
    if count != 10:
        raise ValueError(f"Expected 10 Codex agents, found {count}")
    for directory in (home, target_dir):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError(f"Invalid Codex agents directory: {directory}")
    pairs: list[tuple[Path, Path]] = []
    for name in NAMES:
        source, target = source_dir / f"{name}.toml", target_dir / f"{name}.toml"
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Invalid Codex agent source: {source}")
        lines = source.read_text().splitlines()
        if (
            MARKER not in lines
            or f'name = "{name}"' not in lines
            or not any(line.startswith("description = ") for line in lines)
            or 'developer_instructions = """' not in lines
        ):
            raise ValueError(f"Invalid Codex agent source: {source}")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Refusing non-regular Codex agent target: {target}")
        if target.is_file() and target.read_bytes() != source.read_bytes():
            if MARKER not in target.read_text().splitlines():
                raise ValueError(f"Refusing unrelated Codex agent collision: {target}")
            backup = Path(f"{target}.coderails-backup-{timestamp}")
            if backup.exists() or backup.is_symlink():
                raise ValueError(f"Refusing existing Codex agent backup: {backup}")
        pairs.append((source, target))
    return pairs


def install(root: Path, home: Path, *, dry_run: bool) -> None:
    """Register the independent plugin and atomically copy its native agent definitions."""
    if not shutil.which("codex"):
        raise ValueError("Codex CLI is required")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pairs = preflight(root, home, timestamp)
    if dry_run:
        print(f"would: codex plugin marketplace add {root}")
        print("would: codex plugin add coderails-codex@coderails")
        for source, target in pairs:
            action = "install agent"
            if target.exists():
                action = (
                    "skip identical agent"
                    if target.read_bytes() == source.read_bytes()
                    else "back up and update managed agent"
                )
            print(f"would: {action} {target}")
    else:
        home.mkdir(parents=True, exist_ok=True)
        subprocess.run(["codex", "plugin", "marketplace", "add", str(root)], check=True)
        subprocess.run(["codex", "plugin", "add", "coderails-codex@coderails"], check=True)
        for source, target in pairs:
            if target.exists() and target.read_bytes() == source.read_bytes():
                continue
            if target.exists():
                shutil.copy2(target, f"{target}.coderails-backup-{timestamp}")
            atomic_bytes(target, source.read_bytes())
    if dry_run:
        print(
            "would: after installation, start a fresh Codex session, run /hooks, "
            "and review and trust the Coderails hooks; Codex skips plugin hooks until then."
        )
        return
    print("Codex skips plugin hooks until you review and trust them.")
    print("Start a fresh Codex session, run /hooks, then review and trust the Coderails hooks.")
